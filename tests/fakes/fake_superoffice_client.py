"""Deterministic in-memory FakeSuperOfficeClient for offline contract testing."""

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
from so_mcp.contracts.errors import SuperOfficeEntityNotFoundError


class FakeSuperOfficeClient:
    """Deterministic in-memory implementation of SuperOfficeClient Protocol."""

    def __init__(self) -> None:
        self._tickets: dict[int, TicketDetailDomainDTO] = {}
        self._companies: dict[int, CompanyDomainDTO] = {}
        self._persons: dict[int, PersonDomainDTO] = {}
        self._ticket_messages: dict[int, list[TicketMessageDomainDTO]] = {}
        self._ticket_attachments: dict[int, list[AttachmentMetadata]] = {}

    # Seed helpers for test setup
    def seed_ticket(self, ticket: TicketDetailDomainDTO) -> None:
        """Seed a ticket into the fake repository."""
        self._tickets[ticket.ticket_id] = ticket

    def seed_company(self, company: CompanyDomainDTO) -> None:
        """Seed a company into the fake repository."""
        self._companies[company.company_id] = company

    def seed_person(self, person: PersonDomainDTO) -> None:
        """Seed a person into the fake repository."""
        self._persons[person.person_id] = person

    def seed_message(self, message: TicketMessageDomainDTO) -> None:
        """Seed a ticket message into the fake repository."""
        self._ticket_messages.setdefault(message.ticket_id, []).append(message)

    def seed_attachment(self, ticket_id: int, attachment: AttachmentMetadata) -> None:
        """Seed attachment metadata for a ticket."""
        self._ticket_attachments.setdefault(ticket_id, []).append(attachment)

    # Protocol implementation
    async def get_ticket(self, ticket_id: int) -> TicketDetailDomainDTO:
        """Fetch ticket by ID."""
        if ticket_id not in self._tickets:
            raise SuperOfficeEntityNotFoundError("Ticket", ticket_id)
        return self._tickets[ticket_id]

    async def search_tickets(
        self, criteria: TicketSearchCriteriaDTO
    ) -> SuperOfficePageResponse[TicketSummaryDomainDTO]:
        """Search tickets matching criteria with in-memory pagination."""
        matched: list[TicketSummaryDomainDTO] = []
        for ticket in self._tickets.values():
            if criteria.title and criteria.title.lower() not in ticket.title.lower():
                continue
            if criteria.category and criteria.category.lower() not in ticket.category.lower():
                continue
            if criteria.status and ticket.status.lower() != criteria.status.lower():
                continue
            cat_id = getattr(ticket, "category_id", None)
            if criteria.category_id is not None and cat_id != criteria.category_id:
                continue
            if criteria.customer_id is not None and ticket.customer_id != criteria.customer_id:
                continue

            matched.append(
                TicketSummaryDomainDTO(
                    ticket_id=ticket.ticket_id,
                    title=ticket.title,
                    status=ticket.status,
                    category=ticket.category,
                    priority=ticket.priority,
                    created_at=ticket.created_at,
                    updated_at=ticket.updated_at,
                )
            )

        total_items = len(matched)
        page = max(1, criteria.page)
        page_size = max(1, criteria.page_size)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        page_items = tuple(matched[start_idx:end_idx])
        has_next = end_idx < total_items

        return SuperOfficePageResponse[TicketSummaryDomainDTO](
            items=page_items,
            page=page,
            page_size=page_size,
            total_items=total_items,
            has_next_page=has_next,
        )

    async def get_company(self, company_id: int) -> CompanyDomainDTO:
        """Fetch company by ID."""
        if company_id not in self._companies:
            raise SuperOfficeEntityNotFoundError("Company", company_id)
        return self._companies[company_id]

    async def find_companies(
        self, criteria: CompanySearchCriteriaDTO
    ) -> SuperOfficePageResponse[CompanyDomainDTO]:
        """Search companies matching name or company_id."""
        matched: list[CompanyDomainDTO] = []
        for comp in self._companies.values():
            if criteria.company_id is not None and comp.company_id != criteria.company_id:
                continue
            if criteria.name and criteria.name.lower() not in comp.name.lower():
                continue
            comp_cat = str(getattr(comp, "category", "")).lower()
            if criteria.category and comp_cat and criteria.category.lower() not in comp_cat:
                continue
            matched.append(comp)

        total_items = len(matched)
        page = max(1, criteria.page)
        page_size = max(1, criteria.page_size)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        page_items = tuple(matched[start_idx:end_idx])
        has_next = end_idx < total_items

        return SuperOfficePageResponse[CompanyDomainDTO](
            items=page_items,
            page=page,
            page_size=page_size,
            total_items=total_items,
            has_next_page=has_next,
        )

    async def get_person(self, person_id: int) -> PersonDomainDTO:
        """Fetch person by ID."""
        if person_id not in self._persons:
            raise SuperOfficeEntityNotFoundError("Person", person_id)
        return self._persons[person_id]

    async def find_persons(
        self, criteria: PersonSearchCriteriaDTO
    ) -> SuperOfficePageResponse[PersonDomainDTO]:
        """Search persons matching name, email, or company_id."""
        matched: list[PersonDomainDTO] = []
        for p in self._persons.values():
            if criteria.company_id is not None and p.company_id != criteria.company_id:
                continue
            full_name = f"{p.first_name} {p.last_name}".lower()
            if criteria.name and (criteria.name.lower() not in full_name):
                continue
            email_val = p.email or ""
            if criteria.email and criteria.email.lower() not in email_val.lower():
                continue
            matched.append(p)

        total_items = len(matched)
        page = max(1, criteria.page)
        page_size = max(1, criteria.page_size)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        page_items = tuple(matched[start_idx:end_idx])
        has_next = end_idx < total_items

        return SuperOfficePageResponse[PersonDomainDTO](
            items=page_items,
            page=page,
            page_size=page_size,
            total_items=total_items,
            has_next_page=has_next,
        )

    async def get_ticket_messages(self, ticket_id: int) -> list[TicketMessageDomainDTO]:
        """Fetch messages for ticket."""
        if ticket_id not in self._tickets:
            raise SuperOfficeEntityNotFoundError("Ticket", ticket_id)
        return list(self._ticket_messages.get(ticket_id, []))

    async def list_attachments(self, ticket_id: int) -> list[AttachmentMetadata]:
        """List safe attachment metadata for ticket."""
        if ticket_id not in self._tickets:
            raise SuperOfficeEntityNotFoundError("Ticket", ticket_id)
        return list(self._ticket_attachments.get(ticket_id, []))
