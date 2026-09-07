"""SuperOffice Application Service coordinating domain operations and PII minimization."""

from platform_security.models import AttachmentMetadata
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.contracts.dtos import (
    CompanySearchCriteriaDTO,
    MinimizedCompanyDTO,
    MinimizedPersonDTO,
    MinimizedTicketDetailDTO,
    MinimizedTicketMessageDTO,
    MinimizedTicketSummaryDTO,
    PersonSearchCriteriaDTO,
    SuperOfficePageResponse,
    TicketSearchCriteriaDTO,
)
from so_mcp.contracts.interfaces import SuperOfficeClient


class SuperOfficeApplicationService:
    """Application service for SuperOffice CRM operations with strict PII minimization."""

    def __init__(
        self,
        client: SuperOfficeClient,
        sanitizer: RecursiveOutputSanitizer | None = None,
    ) -> None:
        self._client = client
        self._sanitizer = sanitizer or RecursiveOutputSanitizer()

    async def get_ticket(self, ticket_id: int) -> MinimizedTicketDetailDTO:
        """Retrieve ticket detail with purpose-based field selection and PII scrubbing."""
        domain_ticket = await self._client.get_ticket(ticket_id)
        sanitized_description = str(self._sanitizer.sanitize(domain_ticket.description))

        return MinimizedTicketDetailDTO(
            ticket_id=domain_ticket.ticket_id,
            title=domain_ticket.title,
            status=domain_ticket.status,
            category=domain_ticket.category,
            priority=domain_ticket.priority,
            sanitized_description=sanitized_description,
            sanitized_customer_reference=domain_ticket.customer_reference,
            assigned_agent_id=domain_ticket.assigned_to,
            created_at=domain_ticket.created_at,
        )

    async def search_tickets(
        self, criteria: TicketSearchCriteriaDTO
    ) -> SuperOfficePageResponse[MinimizedTicketSummaryDTO]:
        """Search tickets and return paginated, minimized summary DTOs."""
        domain_page = await self._client.search_tickets(criteria)
        minimized_items = tuple(
            MinimizedTicketSummaryDTO(
                ticket_id=item.ticket_id,
                title=item.title,
                status=item.status,
                category=item.category,
                priority=item.priority,
                created_at=item.created_at,
            )
            for item in domain_page.items
        )
        return SuperOfficePageResponse[MinimizedTicketSummaryDTO](
            items=minimized_items,
            page=domain_page.page,
            page_size=domain_page.page_size,
            total_items=domain_page.total_items,
            has_next_page=domain_page.has_next_page,
        )

    async def get_company(self, company_id: int) -> MinimizedCompanyDTO:
        """Retrieve sanitized company entity."""
        company = await self._client.get_company(company_id)
        return MinimizedCompanyDTO(
            company_id=company.company_id,
            name=company.name,
        )

    async def find_companies(
        self, criteria: CompanySearchCriteriaDTO
    ) -> SuperOfficePageResponse[MinimizedCompanyDTO]:
        """Search companies and return paginated, sanitized company references."""
        domain_page = await self._client.find_companies(criteria)
        minimized_items = tuple(
            MinimizedCompanyDTO(
                company_id=item.company_id,
                name=item.name,
            )
            for item in domain_page.items
        )
        return SuperOfficePageResponse[MinimizedCompanyDTO](
            items=minimized_items,
            page=domain_page.page,
            page_size=domain_page.page_size,
            total_items=domain_page.total_items,
            has_next_page=domain_page.has_next_page,
        )

    async def get_person(self, person_id: int) -> MinimizedPersonDTO:
        """Retrieve person reference with direct customer contact PII omitted."""
        person = await self._client.get_person(person_id)
        display_name = f"{person.first_name} {person.last_name}".strip()
        if not display_name:
            display_name = f"Contact-{person.person_id}"

        return MinimizedPersonDTO(
            person_id=person.person_id,
            display_name=display_name,
            company_id=person.company_id,
        )

    async def find_persons(
        self, criteria: PersonSearchCriteriaDTO
    ) -> SuperOfficePageResponse[MinimizedPersonDTO]:
        """Search persons and return paginated, sanitized person references."""
        domain_page = await self._client.find_persons(criteria)
        minimized_items = tuple(
            MinimizedPersonDTO(
                person_id=item.person_id,
                display_name=f"{item.first_name} {item.last_name}".strip()
                or f"Contact-{item.person_id}",
                company_id=item.company_id,
            )
            for item in domain_page.items
        )
        return SuperOfficePageResponse[MinimizedPersonDTO](
            items=minimized_items,
            page=domain_page.page,
            page_size=domain_page.page_size,
            total_items=domain_page.total_items,
            has_next_page=domain_page.has_next_page,
        )

    async def get_ticket_messages(self, ticket_id: int) -> list[MinimizedTicketMessageDTO]:
        """Retrieve message history with free-text bodies scrubbed for sensitive PII."""
        domain_messages = await self._client.get_ticket_messages(ticket_id)
        return [
            MinimizedTicketMessageDTO(
                message_id=msg.message_id,
                ticket_id=msg.ticket_id,
                author_type=msg.author_type,
                sanitized_body=str(self._sanitizer.sanitize(msg.body)),
                created_at=msg.created_at,
                attachments=msg.attachments,
            )
            for msg in domain_messages
        ]

    async def list_attachments(self, ticket_id: int) -> list[AttachmentMetadata]:
        """List metadata-only attachment records for a ticket."""
        return await self._client.list_attachments(ticket_id)
