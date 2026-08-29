from app.db.tables import role_permissions
from app.models.asset import Asset
from app.models.asset_history import AssetHistory
from app.models.asset_import_batch import AssetImportBatch
from app.models.asset_import_row import AssetImportRow
from app.models.asset_assignment import AssetAssignment
from app.models.asset_type import AssetType
from app.models.ai_suggestion import AiSuggestion
from app.models.approval_request import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.audit_chain_head import AuditChainHead
from app.models.auth_session import AuthSession
from app.models.automation_action_log import AutomationActionLog
from app.models.automation_rule import AutomationRule
from app.models.automation_run import AutomationRun
from app.models.consumer_policy_override import ConsumerPolicyOverride
from app.models.change_approval import ChangeApproval
from app.models.change_history import ChangeHistory
from app.models.change_link import ChangeAssetLink, ChangeTicketLink
from app.models.change_request import ChangeRequest
from app.models.change_governance import (
    CABAgendaItem,
    CABMeeting,
    ChangeImplementationTask,
    ChangePostImplementationReview,
    ChangeWindow,
    StandardChangeModel,
)
from app.models.release_governance import (
    ReleaseChangeLink,
    ReleaseDecision,
    ReleaseDependency,
    ReleaseDeployment,
    ReleaseEnvironment,
    ReleaseGate,
    ReleasePackage,
    ReleaseRecord,
    ReleaseTimeline,
)
from app.models.problem import Problem
from app.models.problem_history import ProblemHistory
from app.models.problem_link import ProblemAssetLink, ProblemChangeLink, ProblemTicketLink
from app.models.problem_governance import (
    KnownErrorUsage,
    ProblemCorrectiveAction,
    ProblemRCA,
    ProblemTrendSignal,
)
from app.models.policy_canary_rollout import PolicyCanaryRollout
from app.models.email_message_log import EmailMessageLog
from app.models.email_channel import (
    EmailAttachment,
    EmailChannel,
    EmailConversation,
    EmailDeliveryEvent,
    EmailInboundMessage,
    EmailWebhookEvent,
)
from app.models.external_system import ExternalSystem
from app.models.external_identity import ExternalIdentity
from app.models.identity_provisioning import (
    IdentityOwnershipTransfer,
    IdentityProvisioningConnector,
    IdentityProvisioningEvent,
    ProvisionedGroup,
    ProvisionedGroupMember,
    ProvisionedIdentity,
)
from app.models.import_job import ImportJob
from app.models.integration_credential import IntegrationCredential
from app.models.integration_event_log import IntegrationEventLog
from app.models.integration_mapping import IntegrationMapping
from app.models.integration_platform import (
    IntegrationApiRequestLog,
    IntegrationApiToken,
    IntegrationServiceAccount,
    OutboundWebhookDelivery,
    OutboundWebhookSubscription,
)
from app.models.workflow_engine import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionEvent,
    WorkflowStepExecution,
    WorkflowVersion,
)
from app.models.custom_fields import (
    CustomFieldSet,
    CustomFieldSetVersion,
    CustomFieldValue,
)
from app.models.job_run import JobRun
from app.models.job_queue_outbox import JobQueueOutbox
from app.models.job_lifecycle_event import JobLifecycleEvent
from app.models.job_event_consumer_delivery import JobEventConsumerDelivery
from app.models.job_event_consumer_offset import JobEventConsumerOffset
from app.models.job_event_autoremediation_policy_state import JobEventAutoremediationPolicyState
from app.models.job_event_runbook_policy_state import JobEventRunbookPolicyState
from app.models.knowledge_article import KnowledgeArticle
from app.models.knowledge_article_feedback import KnowledgeArticleFeedback
from app.models.knowledge_category import KnowledgeCategory
from app.models.knowledge_usage_log import KnowledgeUsageLog
from app.models.notification import Notification
from app.models.notification_preference import NotificationPreference
from app.models.notification_template import NotificationTemplate
from app.models.system_setting import SystemSetting
from app.models.ticket_category import TicketCategory
from app.models.ticket_comment import TicketComment
from app.models.ticket_history import TicketHistory
from app.models.ticket_number_counter import TicketNumberCounter
from app.models.ticket_participant import TicketParticipant
from app.models.ticket_priority import TicketPriority
from app.models.ticket_status import TicketStatus
from app.models.user_role import UserRole
from app.models.permission import Permission
from app.models.policy_approval_request import PolicyApprovalRequest
from app.models.report_snapshot import ReportSnapshot
from app.models.role import Role
from app.models.runbook import Runbook
from app.models.runbook_execution import RunbookExecution
from app.models.saved_report import SavedReport
from app.models.service_catalog import (
    CatalogItem,
    CatalogItemHistory,
    CatalogService,
    ServiceCategory,
    ServiceOffering,
)
from app.models.catalog_user_preference import CatalogUserPreference
from app.models.catalog_form import CatalogFormVersion
from app.models.ci_class import ConfigurationItemClass, ConfigurationItemClassVersion
from app.models.ci_relationship import (
    ConfigurationItemRelationship,
    ConfigurationItemRelationshipType,
)
from app.models.cmdb_reconciliation import (
    CIDuplicateCandidate,
    CMDBFieldOwnership,
    CMDBReconciliationRecord,
    CMDBReconciliationRun,
    CMDBSource,
    CMDBSourceIdentity,
)
from app.models.asset_discovery import (
    AssetDiscoveryConnector,
    AssetDiscoveryRun,
    AssetDiscoveryStaleCandidate,
)
from app.models.cmdb_impact import CMDBImpactAssessment, CMDBImpactCache
from app.models.cmdb_quality import (
    CMDBCertificationCampaign,
    CMDBCertificationItem,
    CMDBQualityFinding,
    CMDBQualitySnapshot,
)
from app.models.major_incident import (
    MajorIncident,
    MajorIncidentAction,
    MajorIncidentChildTicket,
    MajorIncidentPIR,
    MajorIncidentParticipant,
    MajorIncidentUpdate,
)
from app.models.teams_collaboration import (
    TeamsConnector,
    TeamsDelivery,
    TeamsMajorIncidentRoom,
)
from app.models.event_operations import (
    EventCorrelationGroup,
    EventCorrelationPolicy,
    EventGroupActivity,
    EventSource,
    EventSuppressionRule,
    NormalizedEvent,
    MonitoringWebhookReceipt,
)
from app.models.service_request import (
    FulfillmentTask,
    RequestActivity,
    RequestApproval,
    RequestedItem,
    ServiceRequest,
)
from app.models.sla import (
    SlaBusinessCalendar,
    SlaCalendarException,
    SlaPolicy,
    TicketSlaInstance,
    TicketSlaPause,
    TicketSlaTarget,
    TicketSlaTimeline,
)
from app.models.sla_event import SlaEvent
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_governance_action import TicketGovernanceAction
from app.models.ticket_knowledge_link import TicketKnowledgeLink
from app.models.user import User
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.policy_rollout_metrics import PolicyRolloutMetricsHistory, PolicyRolloutMetricsSnapshot
from app.models.metrics_analysis import (
    PolicyMetricsAlertRule,
    PolicyMetricsAnomalyDetection,
    PolicyMetricsHealthAssessment,
)
from app.models.mfa_login_challenge import MfaLoginChallenge
from app.models.user_mfa import UserMfa
from app.models.alert_notifications import (
    PolicyAlertNotification,
    PolicyAlertHistory,
    PolicyNotificationPreference,
)
from app.models.configuration_package import (
    ConfigurationDeployment,
    ConfigurationPackage,
    ConfigurationPackageVersion,
)
from app.models.ai_retrieval import (
    AiRetrievalChunk,
    AiRetrievalDocument,
    AiRetrievalIngestionRun,
    AiRetrievalQueryLog,
)
from app.models.ai_governance import (
    AiEvaluationCase,
    AiEvaluationCaseResult,
    AiEvaluationDataset,
    AiEvaluationRun,
    AiPromptPolicy,
    AiPromptRollout,
    AiPromptVersion,
)
from app.models.ai_runtime_controls import (
    AiDataPolicy,
    AiProviderCircuit,
    AiUsageBudget,
    AiUsageLedger,
)
from app.models.ai_actions import (
    AiActionExecution,
    AiActionPolicy,
    AiActionProposal,
)
from app.models.configuration_center import ConfigurationSettingRevision
from app.models.global_search import SavedSearchView
from app.models.ticket_bulk_plan import TicketBulkPlan
from app.models.tenant_experience import (
    TenantBrandAsset,
    TenantExperienceProfile,
    TenantExperienceRevision,
)
from app.models.localized_content import LocalizedContentVariant
from app.models.data_governance import (
    DataDeletionEvidence,
    DataDeletionRequest,
    DataLegalHold,
    DataRetentionPolicy,
)
from app.models.software_asset import (
    SoftwareInstallation,
    SoftwareLicense,
    SoftwareProduct,
)
