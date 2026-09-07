"""Protocol interfaces for the SuperOffice Integration Adapter boundary."""

from typing import Protocol, runtime_checkable

from platform_security.models import AttachmentMetadata
from so_mcp.contracts.dtos import (
    CompanyDomainDTO,
    CompanySearchCriteriaDTO,
    PersonDomainDTO,
    PersonSearchCriteriaDTO,
    SuperOfficePageResponse,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSearchCriteriaDTO,
    TicketSummaryDomainDTO,
)


@runtime_checkable
class SuperOfficeClient(Protocol):
    """Protocol for external SuperOffice REST WebAPI client implementations."""

    async def get_ticket(self, ticket_id: int) -> TicketDetailDomainDTO:
        """Fetch full ticket domain entity by unique identifier.

        Raises:
            SuperOfficeEntityNotFoundError: If ticket does not exist.
            SuperOfficeIntegrationError: If communication with SuperOffice fails.
        """
        ...

    async def search_tickets(
        self, criteria: TicketSearchCriteriaDTO
    ) -> SuperOfficePageResponse[TicketSummaryDomainDTO]:
        """Search tickets matching structured domain criteria with bounded pagination.

        Raises:
            SuperOfficeIntegrationError: If query execution fails.
        """
        ...

    async def get_company(self, company_id: int) -> CompanyDomainDTO:
        """Fetch company domain entity by unique identifier.

        Raises:
            SuperOfficeEntityNotFoundError: If company does not exist.
            SuperOfficeIntegrationError: If communication with SuperOffice fails.
        """
        ...

    async def find_companies(
        self, criteria: CompanySearchCriteriaDTO
    ) -> SuperOfficePageResponse[CompanyDomainDTO]:
        """Search companies matching name or identifier with bounded pagination.

        Raises:
            SuperOfficeIntegrationError: If query execution fails.
        """
        ...

    async def get_person(self, person_id: int) -> PersonDomainDTO:
        """Fetch contact/person domain entity by unique identifier.

        Raises:
            SuperOfficeEntityNotFoundError: If person does not exist.
            SuperOfficeIntegrationError: If communication with SuperOffice fails.
        """
        ...

    async def find_persons(
        self, criteria: PersonSearchCriteriaDTO
    ) -> SuperOfficePageResponse[PersonDomainDTO]:
        """Search contacts/persons matching name, email, or company with bounded pagination.

        Raises:
            SuperOfficeIntegrationError: If query execution fails.
        """
        ...

    async def get_ticket_messages(self, ticket_id: int) -> list[TicketMessageDomainDTO]:
        """Fetch chronological message exchange history for a ticket.

        Raises:
            SuperOfficeEntityNotFoundError: If parent ticket does not exist.
            SuperOfficeIntegrationError: If query execution fails.
        """
        ...

    async def list_attachments(self, ticket_id: int) -> list[AttachmentMetadata]:
        """List safe metadata for all attachments on a ticket (metadata only; no binary bytes).

        Raises:
            SuperOfficeEntityNotFoundError: If parent ticket does not exist.
            SuperOfficeIntegrationError: If query execution fails.
        """
        ...
