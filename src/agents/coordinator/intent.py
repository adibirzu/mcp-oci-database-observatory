"""Intent classification for user queries."""

import re
from dataclasses import dataclass

from src.core import get_logger
from src.core.types import DatabaseType, IntentResult, IntentType
from src.observability import create_span

logger = get_logger("agents.coordinator.intent")


@dataclass
class IntentPattern:
    """Pattern for intent matching."""

    intent: IntentType
    patterns: list[str]
    keywords: list[str]


# Intent patterns for classification
INTENT_PATTERNS = [
    IntentPattern(
        intent=IntentType.DIAGNOSE,
        patterns=[r"why\s+is", r"what'?s?\s+wrong", r"troubleshoot", r"debug"],
        keywords=["slow", "error", "failing", "issue", "problem", "broken"],
    ),
    IntentPattern(
        intent=IntentType.ANALYZE,
        patterns=[r"analyze", r"review", r"examine", r"investigate"],
        keywords=["performance", "metrics", "statistics", "usage", "trend"],
    ),
    IntentPattern(
        intent=IntentType.OPTIMIZE,
        patterns=[r"optimize", r"improve", r"tune", r"speed\s+up"],
        keywords=["faster", "better", "efficiency", "optimization"],
    ),
    IntentPattern(
        intent=IntentType.MONITOR,
        patterns=[r"monitor", r"watch", r"track", r"check\s+status"],
        keywords=["status", "health", "uptime", "availability"],
    ),
    IntentPattern(
        intent=IntentType.COMPARE,
        patterns=[r"compare", r"difference", r"versus", r"vs\.?"],
        keywords=["between", "comparison", "before", "after"],
    ),
]

# Database type detection patterns
DATABASE_PATTERNS = {
    DatabaseType.ORACLE: [
        r"oracle", r"awr", r"ash", r"rac", r"dataguard", r"opsi",
        r"v\$", r"dba_", r"gv\$", r"autonomous\s+database", r"atp", r"adw",
    ],
    DatabaseType.MYSQL: [
        r"mysql", r"mariadb", r"innodb", r"myisam", r"heatwave",
        r"performance_schema", r"information_schema",
    ],
    DatabaseType.POSTGRES: [
        r"postgres", r"postgresql", r"pg_", r"pgbadger",
        r"vacuum", r"wal", r"replication\s+slot",
    ],
}


class IntentClassifier:
    """Classifies user queries into intents and database types."""

    async def classify(self, query: str) -> IntentResult:
        """Classify a user query.

        Args:
            query: User's natural language query

        Returns:
            Classified intent result
        """
        with create_span("agent.classify_intent", component="coordinator"):
            query_lower = query.lower()

            # Detect intent
            intent, intent_confidence = self._detect_intent(query_lower)

            # Detect database type
            db_type, db_confidence = self._detect_database_type(query_lower)

            # Extract entities
            entities = self._extract_entities(query_lower)

            # Suggest agents based on database type
            suggested_agents = self._suggest_agents(db_type)

            # Calculate overall confidence
            confidence = (intent_confidence + db_confidence) / 2

            logger.info(
                "Query classified",
                intent=intent.value,
                database=db_type if isinstance(db_type, str) else db_type.value,
                confidence=confidence,
            )

            return IntentResult(
                primary_intent=intent,
                database_type=db_type,
                entities=entities,
                confidence=confidence,
                suggested_agents=suggested_agents,
            )

    def _detect_intent(self, query: str) -> tuple[IntentType, float]:
        """Detect the primary intent from the query."""
        best_match: IntentType = IntentType.ANALYZE
        best_score = 0.0

        for pattern in INTENT_PATTERNS:
            score = 0.0

            # Check regex patterns
            for p in pattern.patterns:
                if re.search(p, query):
                    score += 0.4

            # Check keywords
            for keyword in pattern.keywords:
                if keyword in query:
                    score += 0.2

            if score > best_score:
                best_score = score
                best_match = pattern.intent

        # Normalize confidence
        confidence = min(0.95, 0.5 + best_score)

        return best_match, confidence

    def _detect_database_type(
        self,
        query: str,
    ) -> tuple[DatabaseType | str, float]:
        """Detect the target database type from the query."""
        scores: dict[DatabaseType, float] = {
            DatabaseType.ORACLE: 0.0,
            DatabaseType.MYSQL: 0.0,
            DatabaseType.POSTGRES: 0.0,
        }

        for db_type, patterns in DATABASE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query):
                    scores[db_type] += 0.3

        # Find best match
        best_db = max(scores, key=lambda k: scores[k])
        best_score = scores[best_db]

        # Check if multiple databases are mentioned
        significant_dbs = [db for db, score in scores.items() if score > 0.2]

        if len(significant_dbs) > 1:
            return "multi", 0.7

        if best_score > 0.2:
            return best_db, min(0.95, 0.6 + best_score)

        return "unknown", 0.3

    def _extract_entities(self, query: str) -> dict:
        """Extract named entities from the query."""
        entities: dict = {}

        # Extract database names (simple pattern)
        db_name_match = re.search(
            r"(?:database|db)\s+['\"]?(\w+)['\"]?",
            query,
        )
        if db_name_match:
            entities["databases"] = [db_name_match.group(1)]

        # Extract metrics
        metric_keywords = ["cpu", "memory", "io", "wait", "latency", "throughput"]
        found_metrics = [m for m in metric_keywords if m in query]
        if found_metrics:
            entities["metrics"] = found_metrics

        return entities

    def _suggest_agents(
        self,
        db_type: DatabaseType | str,
    ) -> list[str]:
        """Suggest agents based on database type."""
        if db_type == "multi":
            return ["oracle", "mysql", "postgres"]
        elif db_type == "unknown":
            return ["oracle"]  # Default to Oracle
        elif isinstance(db_type, DatabaseType):
            return [db_type.value]
        return []
