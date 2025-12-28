"""OCI Logging service manager."""

import time
from typing import Any

from src.core import get_logger, settings

logger = get_logger("oci.logging.manager")


class LogManager:
    """Manages OCI Logging service resources."""

    def __init__(self) -> None:
        """Initialize log manager."""
        self._logging_client = None
        self._log_group_id: str | None = None
        self._log_id: str | None = None
        self._initialized = False

    @property
    def logging_client(self):
        """Lazy-load OCI Logging Management client."""
        if self._logging_client is None:
            try:
                import oci
                config = oci.config.from_file(
                    file_location=settings.oci_config_file,
                    profile_name=settings.oci_profile,
                )
                self._logging_client = oci.logging.LoggingManagementClient(config)
            except Exception as e:
                logger.error("Failed to create OCI Logging client", error=str(e))
                raise
        return self._logging_client

    async def initialize(
        self,
        log_group_name: str = "oci-database-observatory",
        log_name: str = "application-logs",
    ) -> None:
        """Initialize or get existing log group and log.

        Args:
            log_group_name: Name of the log group
            log_name: Name of the log
        """
        if self._initialized:
            return

        compartment_id = settings.oci_compartment_id
        if not compartment_id:
            logger.warning("OCI_COMPARTMENT_ID not set, skipping OCI Logging setup")
            return

        try:
            # Get or create log group
            self._log_group_id = await self._get_or_create_log_group(
                compartment_id,
                log_group_name,
            )

            # Get or create log
            if self._log_group_id:
                self._log_id = await self._get_or_create_log(
                    self._log_group_id,
                    log_name,
                )

            self._initialized = True
            logger.info(
                "OCI Logging initialized",
                log_group_id=self._log_group_id,
                log_id=self._log_id,
            )
        except Exception as e:
            logger.error("Failed to initialize OCI Logging", error=str(e))

    async def _get_or_create_log_group(
        self,
        compartment_id: str,
        name: str,
    ) -> str | None:
        """Get or create a log group.

        Args:
            compartment_id: OCI compartment ID
            name: Log group name

        Returns:
            Log group OCID or None
        """
        try:
            # List existing log groups
            response = self.logging_client.list_log_groups(
                compartment_id=compartment_id,
                display_name=name,
            )

            if response.data:
                logger.debug("Found existing log group", name=name)
                return response.data[0].id

            # Create new log group
            logger.info("Creating log group", name=name)
            create_response = self.logging_client.create_log_group(
                create_log_group_details=self._build_log_group_details(
                    compartment_id,
                    name,
                ),
            )

            # Wait for creation
            work_request_id = create_response.headers.get("opc-work-request-id")
            if work_request_id:
                await self._wait_for_work_request(work_request_id)

            # Get created log group
            list_response = self.logging_client.list_log_groups(
                compartment_id=compartment_id,
                display_name=name,
            )
            if list_response.data:
                return list_response.data[0].id

        except Exception as e:
            logger.error("Failed to get/create log group", error=str(e))

        return None

    async def _get_or_create_log(
        self,
        log_group_id: str,
        name: str,
    ) -> str | None:
        """Get or create a log.

        Args:
            log_group_id: Log group OCID
            name: Log name

        Returns:
            Log OCID or None
        """
        try:
            # List existing logs
            response = self.logging_client.list_logs(
                log_group_id=log_group_id,
                display_name=name,
            )

            if response.data:
                logger.debug("Found existing log", name=name)
                return response.data[0].id

            # Create new log
            logger.info("Creating log", name=name)
            create_response = self.logging_client.create_log(
                log_group_id=log_group_id,
                create_log_details=self._build_log_details(name),
            )

            # Wait for creation
            work_request_id = create_response.headers.get("opc-work-request-id")
            if work_request_id:
                await self._wait_for_work_request(work_request_id)

            # Get created log
            list_response = self.logging_client.list_logs(
                log_group_id=log_group_id,
                display_name=name,
            )
            if list_response.data:
                return list_response.data[0].id

        except Exception as e:
            logger.error("Failed to get/create log", error=str(e))

        return None

    def _build_log_group_details(
        self,
        compartment_id: str,
        name: str,
    ) -> Any:
        """Build log group creation details.

        Args:
            compartment_id: Compartment OCID
            name: Log group name

        Returns:
            CreateLogGroupDetails
        """
        import oci.logging.models as models

        return models.CreateLogGroupDetails(
            compartment_id=compartment_id,
            display_name=name,
            description="OCI Database Observatory application logs with APM correlation",
            freeform_tags={
                "Application": "oci-database-observatory",
                "Environment": settings.environment,
            },
        )

    def _build_log_details(self, name: str) -> Any:
        """Build log creation details.

        Args:
            name: Log name

        Returns:
            CreateLogDetails
        """
        import oci.logging.models as models

        return models.CreateLogDetails(
            display_name=name,
            log_type="CUSTOM",
            is_enabled=True,
            freeform_tags={
                "Application": "oci-database-observatory",
                "APMCorrelation": "enabled",
            },
        )

    async def _wait_for_work_request(
        self,
        work_request_id: str,
        timeout_seconds: int = 60,
    ) -> None:
        """Wait for a work request to complete.

        Args:
            work_request_id: Work request OCID
            timeout_seconds: Timeout in seconds
        """
        import asyncio
        import oci

        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                response = self.logging_client.get_work_request(work_request_id)
                status = response.data.status
                if status in ["SUCCEEDED", "FAILED", "CANCELED"]:
                    if status != "SUCCEEDED":
                        logger.warning("Work request failed", status=status)
                    return
            except oci.exceptions.ServiceError:
                pass
            await asyncio.sleep(2)

        logger.warning("Work request timed out", work_request_id=work_request_id)

    @property
    def log_group_id(self) -> str | None:
        """Get the log group OCID."""
        return self._log_group_id

    @property
    def log_id(self) -> str | None:
        """Get the log OCID."""
        return self._log_id

    @property
    def is_initialized(self) -> bool:
        """Check if logging is initialized."""
        return self._initialized
