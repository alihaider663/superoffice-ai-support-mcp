"""SuperOffice contract definitions, DTOs, error models, and protocol interfaces."""

from so_mcp.contracts.dtos import (
    CompanyDomainDTO,
    CompanySearchCriteriaDTO,
    MinimizedCompanyDTO,
    MinimizedPersonDTO,
    MinimizedTicketDetailDTO,
    MinimizedTicketMessageDTO,
    MinimizedTicketSummaryDTO,
    PersonDomainDTO,
    PersonSearchCriteriaDTO,
    SuperOfficePageRequest,
    SuperOfficePageResponse,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSearchCriteriaDTO,
    TicketSummaryDomainDTO,
)
from so_mcp.contracts.errors import (
    SuperOfficeAuthenticationError,
    SuperOfficeEntityNotFoundError,
    SuperOfficeIntegrationError,
)
from so_mcp.contracts.interfaces import SuperOfficeClient

__all__ = [
    "CompanyDomainDTO",
    "CompanySearchCriteriaDTO",
    "MinimizedCompanyDTO",
    "MinimizedPersonDTO",
    "MinimizedTicketDetailDTO",
    "MinimizedTicketMessageDTO",
    "MinimizedTicketSummaryDTO",
    "PersonDomainDTO",
    "PersonSearchCriteriaDTO",
    "SuperOfficeAuthenticationError",
    "SuperOfficeClient",
    "SuperOfficeEntityNotFoundError",
    "SuperOfficeIntegrationError",
    "SuperOfficePageRequest",
    "SuperOfficePageResponse",
    "TicketDetailDomainDTO",
    "TicketMessageDomainDTO",
    "TicketSearchCriteriaDTO",
    "TicketSummaryDomainDTO",
]
