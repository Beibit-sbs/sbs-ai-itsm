import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  assignAsset,
  commitAssetImport,
  createCIRelationship,
  createCIRelationshipType,
  createCIClass,
  createCIClassDraft,
  createConfigurationItem,
  type Asset,
  type AssetDetail,
  type AssetHistory,
  type AssetHistoryFeedItem,
  type CIClassField,
  disposeAsset,
  fetchAssetById,
  fetchAssetHistory,
  fetchAssetHistoryFeed,
  fetchAssetImportBatches,
  fetchAssetImportRows,
  fetchAssetsPage,
  fetchCIRelationshipTypes,
  fetchCIClasses,
  fetchCITopology,
  fetchCIFieldOwnership,
  fetchConfigurationItems,
  fetchTenants,
  moveAsset,
  publishCIClass,
  previewAssetImport,
  retireCIRelationship,
  restoreAsset,
  uploadAssetImport,
  updateCIClassDraft,
  verifyAsset,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import CMDBReconciliationPanel from '../components/CMDBReconciliationPanel'
import CMDBImpactPanel from '../components/CMDBImpactPanel'
import CMDBQualityPanel from '../components/CMDBQualityPanel'
import AssetDiscoveryPanel from '../components/AssetDiscoveryPanel'
import EntityCustomFieldsPanel from '../components/EntityCustomFieldsPanel'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'


type AssetsMode = 'registry' | 'cmdb' | 'topology' | 'reconciliation' | 'discovery' | 'quality' | 'import' | 'inventory' | 'rooms' | 'responsible' | 'disposal' | 'history'
type DetailTab = 'overview' | 'accounting' | 'location' | 'responsible' | 'relationships' | 'impact' | 'governance' | 'tickets' | 'history'
type ActionModalType = 'move' | 'assign' | 'verify' | 'dispose' | 'restore' | null

const statusRu: Record<string, string> = {
  active: 'Активный',
  inactive: 'Неактивный',
  disposed: 'Списан',
  in_stock: 'В запасах',
  in_use: 'В эксплуатации',
  in_repair: 'В ремонте',
  maintenance: 'На обслуживании',
  broken: 'Неисправен',
}

const verificationRu: Record<string, string> = {
  verified: 'Проверено',
  pending: 'Ожидает проверки',
  needs_location: 'Требует кабинета',
  failed: 'Ошибка',
  unknown: 'Неизвестно',
}

const sourceRu: Record<string, string> = {
  excel_import: 'Импорт Excel',
  cmdb_manual: 'CMDB',
}

const fieldTypeLabels: Record<CIClassField['type'], string> = {
  text: 'Текст',
  textarea: 'Многострочный текст',
  integer: 'Целое число',
  number: 'Число',
  boolean: 'Да / нет',
  date: 'Дата',
  datetime: 'Дата и время',
  email: 'Email',
  select: 'Выбор',
  multiselect: 'Множественный выбор',
}

function canManageCmdb(session: ReturnType<typeof useAuth>['session']) {
  return session?.user.role === 'saas_root'
    || Boolean(session?.user.permissions.includes('assets.update'))
}

function canVerifyCmdb(session: ReturnType<typeof useAuth>['session']) {
  return session?.user.role === 'saas_root'
    || Boolean(session?.user.permissions.includes('assets.verify'))
}

function mutationError(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function ruStatus(value: string | null | undefined) {
  const key = String(value ?? '').toLowerCase()
  if (!key) return '—'
  return statusRu[key] ?? value ?? '—'
}

function ruVerification(value: string | null | undefined) {
  const key = String(value ?? '').toLowerCase()
  if (!key) return '—'
  return verificationRu[key] ?? value ?? '—'
}

function ruSource(value: string | null | undefined) {
  const key = String(value ?? '').toLowerCase()
  if (!key) return 'manual'
  return sourceRu[key] ?? value ?? 'manual'
}

function roomLabel(asset: Asset) {
  if (asset.room && asset.room.trim()) return asset.room
  return 'Кабинет не указан'
}

export default function AssetsPage() {
  const { session } = useAuth()
  const { formatDateTime, formatNumber, translate } = useTenantExperience()
  const formatDate = (value: string | null | undefined) => formatDateTime(value, {
    dateStyle: 'medium',
  })
  const formatMoney = (value: number | null | undefined) => value == null
    ? '—'
    : formatNumber(value, { maximumFractionDigits: 2 })
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const [activeMode, setActiveMode] = useState<AssetsMode>('registry')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)

  const [typeFilter, setTypeFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [roomFilter, setRoomFilter] = useState('ALL')
  const [responsibleFilter, setResponsibleFilter] = useState('ALL')
  const [molFilter, setMolFilter] = useState('ALL')
  const [yearFilter, setYearFilter] = useState('ALL')
  const [sourceFilter, setSourceFilter] = useState('ALL')
  const [verificationFilter, setVerificationFilter] = useState('ALL')

  const [cmdbTenantId, setCmdbTenantId] = useState(session?.user.tenant_id ?? '')
  const [classForm, setClassForm] = useState({
    parent_class_id: '',
    code: '',
    name: '',
    description: '',
  })
  const [classFields, setClassFields] = useState<CIClassField[]>([])
  const [fieldDraft, setFieldDraft] = useState<CIClassField>({
    key: '',
    label: '',
    type: 'text',
    required: false,
    description: '',
    options: [],
  })
  const [fieldOptions, setFieldOptions] = useState('')
  const [publishReason, setPublishReason] = useState<Record<string, string>>({})
  const [editingClassId, setEditingClassId] = useState<string | null>(null)
  const [editingClassFields, setEditingClassFields] = useState<CIClassField[]>([])
  const [editFieldDraft, setEditFieldDraft] = useState<CIClassField>({
    key: '',
    label: '',
    type: 'text',
    required: false,
    description: '',
    options: [],
  })
  const [editFieldOptions, setEditFieldOptions] = useState('')
  const [ciForm, setCiForm] = useState({
    ci_class_id: '',
    asset_tag: '',
    name: '',
    inventory_number: '',
    serial_number: '',
    manufacturer: '',
    model: '',
    lifecycle_status: 'ACTIVE' as 'PLANNING' | 'ORDERED' | 'IN_STOCK' | 'ACTIVE' | 'MAINTENANCE' | 'RETIRED' | 'DISPOSED',
    support_group: 'Service Desk',
    criticality: 'MEDIUM' as Asset['criticality'],
    environment: 'PRODUCTION' as Asset['environment'],
    location: 'Location unknown',
    description: '',
  })
  const [ciAttributes, setCiAttributes] = useState<Record<string, unknown>>({})
  const [topologyRootId, setTopologyRootId] = useState('')
  const [topologyDirection, setTopologyDirection] = useState<'upstream' | 'downstream' | 'both'>('both')
  const [topologyDepth, setTopologyDepth] = useState(4)
  const [relationshipForm, setRelationshipForm] = useState({
    relationship_type_id: '',
    source_ci_id: '',
    target_ci_id: '',
    description: '',
  })
  const [relationshipTypeForm, setRelationshipTypeForm] = useState({
    code: '',
    name: '',
    forward_label: '',
    reverse_label: '',
    description: '',
    source_class_id: '',
    target_class_id: '',
    source_cardinality: 'MANY' as 'ONE' | 'MANY',
    target_cardinality: 'MANY' as 'ONE' | 'MANY',
    allow_cycles: false,
  })
  const [retireReason, setRetireReason] = useState<Record<string, string>>({})

  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<DetailTab>('overview')

  const [actionModalType, setActionModalType] = useState<ActionModalType>(null)
  const [actionAssetId, setActionAssetId] = useState<string | null>(null)

  const [moveForm, setMoveForm] = useState({ building: '', floor: '', room: '', location_label: '', comment: '' })
  const [assignForm, setAssignForm] = useState({ responsible_person_name: '', responsible_department: '', mol_name: '', mol_department: '', comment: '' })
  const [verifyForm, setVerifyForm] = useState({ verification_status: 'verified', comment: '' })
  const [disposeForm, setDisposeForm] = useState({ writeoff_reason: '', comment: '', confirm: false })
  const [restoreComment, setRestoreComment] = useState('')

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)

  const [historyAction, setHistoryAction] = useState('ALL')
  const [historyActor, setHistoryActor] = useState('')
  const [historyAsset, setHistoryAsset] = useState('')
  const [historyDateFrom, setHistoryDateFrom] = useState('')
  const [historyDateTo, setHistoryDateTo] = useState('')

  useEffect(() => {
    const linkedAssetId = searchParams.get('asset')
    if (!linkedAssetId) return
    setActiveMode('registry')
    setDetailTab('overview')
    setSelectedAssetId(linkedAssetId)
    const next = new URLSearchParams(searchParams)
    next.delete('asset')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim())
      setPage(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [search])

  const assetsQuery = useQuery({
    queryKey: [
      'assets',
      session?.access_token,
      debouncedSearch,
      typeFilter,
      statusFilter,
      roomFilter,
      responsibleFilter,
      molFilter,
      yearFilter,
      sourceFilter,
      verificationFilter,
      page,
      pageSize,
    ],
    queryFn: () =>
      fetchAssetsPage(session?.access_token ?? '', {
        q: debouncedSearch || undefined,
        asset_type: typeFilter,
        status: statusFilter,
        room: roomFilter,
        responsible_person_name: responsibleFilter,
        mol_name: molFilter,
        purchase_year: yearFilter === 'ALL' ? undefined : Number(yearFilter),
        source: sourceFilter,
        verification_status: verificationFilter,
        page,
        page_size: pageSize,
      }),
    enabled: Boolean(session?.access_token),
  })

  const tenantsQuery = useQuery({
    queryKey: ['cmdb-tenants', session?.access_token],
    queryFn: () => fetchTenants(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token)
      && ['cmdb', 'topology', 'reconciliation', 'discovery', 'quality'].includes(activeMode)
      && session?.user.role === 'saas_root',
  })

  const ciClassesQuery = useQuery({
    queryKey: ['cmdb-classes', session?.access_token, cmdbTenantId],
    queryFn: () => fetchCIClasses(
      session?.access_token ?? '',
      cmdbTenantId || undefined,
    ),
    enabled: Boolean(session?.access_token)
      && ['cmdb', 'topology', 'reconciliation', 'discovery', 'quality'].includes(activeMode),
  })

  const configurationItemsQuery = useQuery({
    queryKey: ['cmdb-items', session?.access_token, cmdbTenantId],
    queryFn: () => fetchConfigurationItems(
      session?.access_token ?? '',
      cmdbTenantId || undefined,
    ),
    enabled: Boolean(session?.access_token)
      && activeMode === 'topology'
      && (session?.user.role !== 'saas_root' || Boolean(cmdbTenantId)),
  })

  const relationshipTypesQuery = useQuery({
    queryKey: ['cmdb-relationship-types', session?.access_token, cmdbTenantId],
    queryFn: () => fetchCIRelationshipTypes(
      session?.access_token ?? '',
      cmdbTenantId || undefined,
    ),
    enabled: Boolean(session?.access_token)
      && activeMode === 'topology'
      && (session?.user.role !== 'saas_root' || Boolean(cmdbTenantId)),
  })

  const topologyQuery = useQuery({
    queryKey: [
      'cmdb-topology',
      session?.access_token,
      topologyRootId,
      topologyDirection,
      topologyDepth,
    ],
    queryFn: () => fetchCITopology(
      session?.access_token ?? '',
      topologyRootId,
      topologyDirection,
      topologyDepth,
    ),
    enabled: Boolean(
      session?.access_token
      && activeMode === 'topology'
      && topologyRootId,
    ),
  })

  const detailQuery = useQuery({
    queryKey: ['asset-detail', session?.access_token, selectedAssetId],
    queryFn: () => fetchAssetById(session?.access_token ?? '', selectedAssetId ?? ''),
    enabled: Boolean(session?.access_token && selectedAssetId),
  })

  const detailHistoryQuery = useQuery({
    queryKey: ['asset-history', session?.access_token, selectedAssetId],
    queryFn: () => fetchAssetHistory(session?.access_token ?? '', selectedAssetId ?? ''),
    enabled: Boolean(session?.access_token && selectedAssetId),
  })

  const detailTopologyQuery = useQuery({
    queryKey: [
      'asset-topology',
      session?.access_token,
      selectedAssetId,
    ],
    queryFn: () => fetchCITopology(
      session?.access_token ?? '',
      selectedAssetId ?? '',
      'both',
      1,
    ),
    enabled: Boolean(
      session?.access_token
      && selectedAssetId
      && detailTab === 'relationships'
      && detailQuery.data?.ci_class_id,
    ),
  })

  const detailOwnershipQuery = useQuery({
    queryKey: [
      'cmdb-field-ownership',
      session?.access_token,
      selectedAssetId,
    ],
    queryFn: () => fetchCIFieldOwnership(
      session?.access_token ?? '',
      selectedAssetId ?? '',
    ),
    enabled: Boolean(
      session?.access_token
      && selectedAssetId
      && detailTab === 'governance'
      && detailQuery.data?.ci_class_id,
    ),
  })

  const historyFeedQuery = useQuery({
    queryKey: ['asset-history-feed', session?.access_token, historyAction, historyActor, historyAsset, historyDateFrom, historyDateTo],
    queryFn: () =>
      fetchAssetHistoryFeed(session?.access_token ?? '', {
        action: historyAction,
        actor: historyActor || undefined,
        asset_q: historyAsset || undefined,
        date_from: historyDateFrom ? new Date(historyDateFrom).toISOString() : undefined,
        date_to: historyDateTo ? new Date(historyDateTo).toISOString() : undefined,
        limit: 200,
      }),
    enabled: Boolean(session?.access_token) && activeMode === 'history',
  })

  const batchesQuery = useQuery({
    queryKey: ['asset-import-batches', session?.access_token],
    queryFn: () => fetchAssetImportBatches(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && activeMode === 'import',
  })

  const rowsQuery = useQuery({
    queryKey: ['asset-import-rows', session?.access_token, activeBatchId],
    queryFn: () => fetchAssetImportRows(session?.access_token ?? '', activeBatchId ?? ''),
    enabled: Boolean(session?.access_token && activeBatchId) && activeMode === 'import',
  })

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => uploadAssetImport(session?.access_token ?? '', file),
    onSuccess: async (batch) => {
      setActiveBatchId(batch.id)
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
    },
  })

  const previewMutation = useMutation({
    mutationFn: async (batchId: string) => previewAssetImport(session?.access_token ?? '', { batch_id: batchId, dry_run: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-rows'] })
    },
  })

  const commitMutation = useMutation({
    mutationFn: async (batchId: string) => commitAssetImport(session?.access_token ?? '', batchId, { dry_run: false }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-rows'] })
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  const moveMutation = useMutation({
    mutationFn: async (assetId: string) => moveAsset(session?.access_token ?? '', assetId, moveForm),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const assignMutation = useMutation({
    mutationFn: async (assetId: string) => assignAsset(session?.access_token ?? '', assetId, assignForm),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const verifyMutation = useMutation({
    mutationFn: async (assetId: string) => verifyAsset(session?.access_token ?? '', assetId, verifyForm),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const disposeMutation = useMutation({
    mutationFn: async (assetId: string) => disposeAsset(session?.access_token ?? '', assetId, { writeoff_reason: disposeForm.writeoff_reason, comment: disposeForm.comment }),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const restoreMutation = useMutation({
    mutationFn: async (assetId: string) => restoreAsset(session?.access_token ?? '', assetId, { comment: restoreComment }),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const createClassMutation = useMutation({
    mutationFn: () => createCIClass(session?.access_token ?? '', {
      tenant_id: session?.user.role === 'saas_root' ? cmdbTenantId : undefined,
      parent_class_id: classForm.parent_class_id || null,
      code: classForm.code,
      name: classForm.name,
      description: classForm.description || null,
      schema: { fields: classFields },
    }),
    onSuccess: async (created) => {
      setClassForm({ parent_class_id: '', code: '', name: '', description: '' })
      setClassFields([])
      setPublishReason((current) => ({
        ...current,
        [created.id]: 'Класс проверен владельцем CMDB',
      }))
      await queryClient.invalidateQueries({ queryKey: ['cmdb-classes'] })
    },
  })

  const publishClassMutation = useMutation({
    mutationFn: (classId: string) => {
      const ciClass = (ciClassesQuery.data ?? []).find((entry) => entry.id === classId)
      if (!ciClass?.draft_version) throw new Error('Черновик класса не найден')
      return publishCIClass(session?.access_token ?? '', classId, {
        expected_revision: ciClass.draft_version.revision,
        reason: publishReason[classId] || 'Класс проверен владельцем CMDB',
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['cmdb-classes'] })
    },
  })

  const createClassDraftMutation = useMutation({
    mutationFn: (classId: string) => createCIClassDraft(
      session?.access_token ?? '',
      classId,
    ),
    onSuccess: async (updated) => {
      setEditingClassId(updated.id)
      setEditingClassFields(updated.draft_version?.schema.fields ?? [])
      await queryClient.invalidateQueries({ queryKey: ['cmdb-classes'] })
    },
  })

  const updateClassDraftMutation = useMutation({
    mutationFn: (classId: string) => {
      const ciClass = ciClasses.find((entry) => entry.id === classId)
      if (!ciClass?.draft_version) throw new Error('Черновик класса не найден')
      return updateCIClassDraft(session?.access_token ?? '', classId, {
        expected_revision: ciClass.draft_version.revision,
        schema: { fields: editingClassFields },
      })
    },
    onSuccess: async () => {
      setEditingClassId(null)
      setEditingClassFields([])
      await queryClient.invalidateQueries({ queryKey: ['cmdb-classes'] })
    },
  })

  const createCiMutation = useMutation({
    mutationFn: () => createConfigurationItem(session?.access_token ?? '', {
      ...ciForm,
      inventory_number: ciForm.inventory_number || null,
      serial_number: ciForm.serial_number || null,
      manufacturer: ciForm.manufacturer || null,
      model: ciForm.model || null,
      description: ciForm.description || null,
      attributes: ciAttributes,
    }),
    onSuccess: async () => {
      setCiForm((current) => ({
        ...current,
        asset_tag: '',
        name: '',
        inventory_number: '',
        serial_number: '',
        manufacturer: '',
        model: '',
        description: '',
      }))
      setCiAttributes({})
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  const createRelationshipTypeMutation = useMutation({
    mutationFn: () => createCIRelationshipType(
      session?.access_token ?? '',
      {
        tenant_id: session?.user.role === 'saas_root'
          ? cmdbTenantId
          : undefined,
        code: relationshipTypeForm.code,
        name: relationshipTypeForm.name,
        forward_label: relationshipTypeForm.forward_label,
        reverse_label: relationshipTypeForm.reverse_label,
        description: relationshipTypeForm.description || null,
        source_class_id: relationshipTypeForm.source_class_id || null,
        target_class_id: relationshipTypeForm.target_class_id || null,
        source_cardinality: relationshipTypeForm.source_cardinality,
        target_cardinality: relationshipTypeForm.target_cardinality,
        allow_self_relationship: false,
        allow_cycles: relationshipTypeForm.allow_cycles,
      },
    ),
    onSuccess: async (created) => {
      setRelationshipTypeForm({
        code: '',
        name: '',
        forward_label: '',
        reverse_label: '',
        description: '',
        source_class_id: '',
        target_class_id: '',
        source_cardinality: 'MANY',
        target_cardinality: 'MANY',
        allow_cycles: false,
      })
      setRelationshipForm((current) => ({
        ...current,
        relationship_type_id: created.id,
      }))
      await queryClient.invalidateQueries({
        queryKey: ['cmdb-relationship-types'],
      })
    },
  })

  const createRelationshipMutation = useMutation({
    mutationFn: () => createCIRelationship(
      session?.access_token ?? '',
      {
        relationship_type_id: relationshipForm.relationship_type_id,
        source_ci_id: relationshipForm.source_ci_id,
        target_ci_id: relationshipForm.target_ci_id,
        description: relationshipForm.description || null,
      },
    ),
    onSuccess: async (created) => {
      setTopologyRootId(created.source.id)
      setRelationshipForm((current) => ({
        ...current,
        description: '',
      }))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['cmdb-topology'] }),
        queryClient.invalidateQueries({
          queryKey: ['cmdb-relationship-types'],
        }),
        queryClient.invalidateQueries({ queryKey: ['asset-history'] }),
      ])
    },
  })

  const retireRelationshipMutation = useMutation({
    mutationFn: (relationshipId: string) => {
      const relationship = topologyQuery.data?.edges.find(
        (entry) => entry.id === relationshipId,
      )
      if (!relationship) throw new Error('Связь CI не найдена')
      return retireCIRelationship(
        session?.access_token ?? '',
        relationship.id,
        relationship.version,
        retireReason[relationship.id] || 'Связь выведена из service model',
      )
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['cmdb-topology'] }),
        queryClient.invalidateQueries({
          queryKey: ['cmdb-relationship-types'],
        }),
        queryClient.invalidateQueries({ queryKey: ['asset-history'] }),
      ])
    },
  })

  const assets = assetsQuery.data?.items ?? []
  const total = assetsQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const selectedAsset: AssetDetail | null = detailQuery.data ?? null
  const selectedAssetHistory: AssetHistory[] = detailHistoryQuery.data ?? []
  const historyFeed: AssetHistoryFeedItem[] = historyFeedQuery.data ?? []
  const activeBatch = (batchesQuery.data ?? []).find((item) => item.id === activeBatchId)
  const ciClasses = ciClassesQuery.data ?? []
  const publishedClasses = ciClasses.filter((entry) => entry.published_version)
  const selectedCiClass = publishedClasses.find(
    (entry) => entry.id === ciForm.ci_class_id,
  ) ?? null
  const configurationItems = configurationItemsQuery.data ?? []
  const relationshipTypes = relationshipTypesQuery.data ?? []
  const activeRelationshipTypes = relationshipTypes.filter(
    (entry) => entry.status === 'ACTIVE',
  )
  const topology = topologyQuery.data

  useEffect(() => {
    if (!activeBatchId && batchesQuery.data?.length) {
      setActiveBatchId(batchesQuery.data[0].id)
    }
  }, [activeBatchId, batchesQuery.data])

  useEffect(() => {
    if (
      session?.user.role === 'saas_root'
      && !cmdbTenantId
      && tenantsQuery.data?.length
    ) {
      setCmdbTenantId(tenantsQuery.data[0].id)
    }
  }, [cmdbTenantId, session?.user.role, tenantsQuery.data])

  useEffect(() => {
    if (!ciForm.ci_class_id && publishedClasses.length) {
      setCiForm((current) => ({
        ...current,
        ci_class_id: publishedClasses[0].id,
      }))
    }
  }, [ciForm.ci_class_id, publishedClasses])

  useEffect(() => {
    if (!topologyRootId && configurationItems.length) {
      setTopologyRootId(configurationItems[0].id)
    }
    if (!relationshipForm.source_ci_id && configurationItems.length) {
      setRelationshipForm((current) => ({
        ...current,
        source_ci_id: configurationItems[0].id,
        target_ci_id: configurationItems[1]?.id ?? '',
      }))
    }
  }, [
    configurationItems,
    relationshipForm.source_ci_id,
    topologyRootId,
  ])

  useEffect(() => {
    if (!relationshipForm.relationship_type_id && activeRelationshipTypes.length) {
      setRelationshipForm((current) => ({
        ...current,
        relationship_type_id: activeRelationshipTypes[0].id,
      }))
    }
  }, [activeRelationshipTypes, relationshipForm.relationship_type_id])

  const typeOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.asset_type))).sort()], [assets])
  const statusOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.status))).sort()], [assets])
  const roomOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => roomLabel(a)))).sort()], [assets])
  const responsibleOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.responsible_person_name).filter(Boolean) as string[])).sort()], [assets])
  const molOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.mol_name).filter(Boolean) as string[])).sort()], [assets])
  const yearOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.purchase_year).filter((v): v is number => typeof v === 'number'))).sort((a, b) => b - a).map(String)], [assets])
  const sourceOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.source ?? 'manual'))).sort()], [assets])
  const verificationOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.verification_status).filter(Boolean) as string[])).sort()], [assets])

  const inventoryStats = useMemo(() => {
    const verified = assets.filter((a) => (a.verification_status ?? '').toLowerCase() === 'verified').length
    const needsLocation = assets.filter((a) => (a.verification_status ?? '').toLowerCase() === 'needs_location').length
    const needsVerification = assets.filter((a) => ['pending', 'unknown', 'needs_location'].includes((a.verification_status ?? '').toLowerCase())).length
    const disposed = assets.filter((a) => (a.status ?? '').toLowerCase() === 'disposed').length
    const excel = assets.filter((a) => (a.source ?? '').toLowerCase() === 'excel_import').length
    const withoutMol = assets.filter((a) => !(a.mol_name && a.mol_name.trim())).length
    const withoutRoom = assets.filter((a) => roomLabel(a) === 'Кабинет не указан').length
    return { verified, needsLocation, needsVerification, disposed, excel, withoutMol, withoutRoom }
  }, [assets])

  const roomsGroups = useMemo(() => {
    const map = new Map<string, Asset[]>()
    for (const asset of assets) {
      const key = roomLabel(asset)
      if (!map.has(key)) map.set(key, [])
      map.get(key)?.push(asset)
    }
    return Array.from(map.entries()).map(([room, items]) => {
      const types = Array.from(new Set(items.map((a) => a.asset_type))).join(', ')
      const responsibles = Array.from(new Set(items.map((a) => a.responsible_person_name).filter(Boolean) as string[])).join(', ')
      return {
        room,
        count: items.length,
        types,
        responsibles: responsibles || '—',
        needsVerification: items.filter((a) => ['pending', 'unknown', 'needs_location'].includes((a.verification_status ?? '').toLowerCase())).length,
      }
    }).sort((a, b) => b.count - a.count)
  }, [assets])

  const responsibleGroups = useMemo(() => {
    const map = new Map<string, Asset[]>()
    for (const asset of assets) {
      const key = asset.responsible_person_name || asset.mol_name || 'Не назначен'
      if (!map.has(key)) map.set(key, [])
      map.get(key)?.push(asset)
    }
    return Array.from(map.entries()).map(([responsible, items]) => ({
      responsible,
      department: items[0]?.responsible_department || items[0]?.mol_department || '—',
      count: items.length,
      residual: items.reduce((sum, item) => sum + Number(item.residual_cost ?? item.residual_value ?? 0), 0),
      withoutRoom: items.filter((item) => roomLabel(item) === 'Кабинет не указан').length,
      disposed: items.filter((item) => (item.status ?? '').toLowerCase() === 'disposed').length,
    })).sort((a, b) => b.count - a.count)
  }, [assets])

  const disposedAssets = useMemo(() => assets.filter((a) => (a.status ?? '').toLowerCase() === 'disposed'), [assets])

  const openActionModal = (type: ActionModalType, assetId: string) => {
    setActionAssetId(assetId)
    setActionModalType(type)
  }

  const closeActionModal = () => {
    setActionModalType(null)
    setActionAssetId(null)
    setDisposeForm({ writeoff_reason: '', comment: '', confirm: false })
  }

  const closeDetail = () => {
    setSelectedAssetId(null)
    setDetailTab('overview')
  }

  const detailDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(selectedAssetId),
    closeDetail,
  )
  const actionDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(actionModalType),
    closeActionModal,
  )

  const addClassField = () => {
    if (!fieldDraft.key.trim() || !fieldDraft.label.trim()) return
    const options = ['select', 'multiselect'].includes(fieldDraft.type)
      ? fieldOptions.split(',').map((entry) => entry.trim()).filter(Boolean).map((entry) => {
        const [rawValue, rawLabel] = entry.split('=')
        const label = (rawLabel || rawValue).trim()
        const value = rawValue.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_')
        return { value, label }
      })
      : []
    setClassFields((current) => [...current, {
      ...fieldDraft,
      key: fieldDraft.key.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_'),
      label: fieldDraft.label.trim(),
      description: fieldDraft.description.trim(),
      options,
    }])
    setFieldDraft({
      key: '',
      label: '',
      type: 'text',
      required: false,
      description: '',
      options: [],
    })
    setFieldOptions('')
  }

  const addEditClassField = () => {
    if (!editFieldDraft.key.trim() || !editFieldDraft.label.trim()) return
    const options = ['select', 'multiselect'].includes(editFieldDraft.type)
      ? editFieldOptions.split(',').map((entry) => entry.trim()).filter(Boolean).map((entry) => {
        const [rawValue, rawLabel] = entry.split('=')
        return {
          value: rawValue.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_'),
          label: (rawLabel || rawValue).trim(),
        }
      })
      : []
    setEditingClassFields((current) => [...current, {
      ...editFieldDraft,
      key: editFieldDraft.key.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_'),
      label: editFieldDraft.label.trim(),
      description: editFieldDraft.description.trim(),
      options,
    }])
    setEditFieldDraft({
      key: '',
      label: '',
      type: 'text',
      required: false,
      description: '',
      options: [],
    })
    setEditFieldOptions('')
  }

  const updateCiAttribute = (field: CIClassField, rawValue: string | boolean) => {
    let value: unknown = rawValue
    if (field.type === 'integer' || field.type === 'number') {
      value = rawValue === '' ? '' : Number(rawValue)
    }
    setCiAttributes((current) => ({ ...current, [field.key]: value }))
  }

  return (
    <LocalizedContent>
    <AppShell title="Активы и CMDB" subtitle="Управляемые конфигурационные единицы, классы, жизненный цикл, импорт и инвентаризация.">
      <QueryFailureNotice
        title="Часть данных Assets & CMDB недоступна."
        sources={[
          { label: translate('активы'), query: assetsQuery },
          { label: translate('организации'), query: tenantsQuery },
          { label: 'CI classes', query: ciClassesQuery },
          { label: 'configuration items', query: configurationItemsQuery },
          { label: 'relationship types', query: relationshipTypesQuery },
          { label: 'topology', query: topologyQuery },
          { label: translate('детали актива'), query: detailQuery },
          { label: translate('история актива'), query: detailHistoryQuery },
          { label: translate('topology актива'), query: detailTopologyQuery },
          { label: 'ownership', query: detailOwnershipQuery },
          { label: 'history feed', query: historyFeedQuery },
          { label: 'import batches', query: batchesQuery },
          { label: 'import rows', query: rowsQuery },
        ]}
      />
      <nav className="module-subnav" aria-label="Assets navigation">
        <button type="button" className={`module-subnav-tab ${activeMode === 'registry' ? 'active' : ''}`} onClick={() => setActiveMode('registry')}>Реестр активов</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'cmdb' ? 'active' : ''}`} onClick={() => setActiveMode('cmdb')}>Классы CMDB</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'topology' ? 'active' : ''}`} onClick={() => setActiveMode('topology')}>Карта сервисов</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'reconciliation' ? 'active' : ''}`} onClick={() => setActiveMode('reconciliation')}>Источники CMDB</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'quality' ? 'active' : ''}`} onClick={() => setActiveMode('quality')}>Качество CMDB</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'import' ? 'active' : ''}`} onClick={() => setActiveMode('import')}>Импорт Excel</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'inventory' ? 'active' : ''}`} onClick={() => setActiveMode('inventory')}>Инвентаризация</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'rooms' ? 'active' : ''}`} onClick={() => setActiveMode('rooms')}>Кабинеты</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'responsible' ? 'active' : ''}`} onClick={() => setActiveMode('responsible')}>Ответственные</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'disposal' ? 'active' : ''}`} onClick={() => setActiveMode('disposal')}>Списание</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'history' ? 'active' : ''}`} onClick={() => setActiveMode('history')}>История</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'discovery' ? 'active' : ''}`} onClick={() => setActiveMode('discovery')}>Asset Discovery</button>
      </nav>

      {activeMode === 'registry' ? (
        <>
          <section className="foundation-card table-toolbar">
            <div className="table-filters" style={{ gridTemplateColumns: 'repeat(6, minmax(0,1fr))' }}>
              <label className="inline-field"><span>Поиск</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Инв. №, имя, серийный номер" /></label>
              <label className="inline-field"><span>Тип</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>{typeOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Статус</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>{statusOptions.map((item) => <option key={item} value={item}>{ruStatus(item)}</option>)}</select></label>
              <label className="inline-field"><span>Кабинет</span><select value={roomFilter} onChange={(event) => setRoomFilter(event.target.value)}>{roomOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Ответственный</span><select value={responsibleFilter} onChange={(event) => setResponsibleFilter(event.target.value)}>{responsibleOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>МОЛ</span><select value={molFilter} onChange={(event) => setMolFilter(event.target.value)}>{molOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Год покупки</span><select value={yearFilter} onChange={(event) => setYearFilter(event.target.value)}>{yearOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Источник</span><select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>{sourceOptions.map((item) => <option key={item} value={item}>{ruSource(item)}</option>)}</select></label>
              <label className="inline-field"><span>Проверка</span><select value={verificationFilter} onChange={(event) => setVerificationFilter(event.target.value)}>{verificationOptions.map((item) => <option key={item} value={item}>{ruVerification(item)}</option>)}</select></label>
              <label className="inline-field"><span>page_size</span><select value={String(pageSize)} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}><option value="25">25</option><option value="50">50</option><option value="100">100</option></select></label>
            </div>
          </section>

          <section className="section-card">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Инв. №</th><th>Наименование</th><th>Класс / тип</th><th>Lifecycle</th><th>Критичность</th><th>Кабинет</th><th>Ответственный</th><th>МОЛ</th><th>Остаточная стоимость</th><th>Проверка</th><th>Источник</th><th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {assetsQuery.isPending ? <tr><td colSpan={12}><p className="loading-state">Загрузка данных...</p></td></tr> : null}
                  {!assetsQuery.isPending && assets.length === 0 ? <tr><td colSpan={12}><p className="empty-state">Данных пока нет.</p></td></tr> : null}
                  {assets.map((asset) => (
                    <tr key={asset.id}>
                      <td>{asset.inventory_number ?? asset.asset_tag}</td>
                      <td>{asset.name}</td>
                      <td>{asset.ci_class_name ?? asset.asset_type}</td>
                      <td>{asset.ci_class_id ? asset.lifecycle_status : ruStatus(asset.status)}</td>
                      <td>{asset.criticality}</td>
                      <td>{asset.room && asset.room.trim() ? asset.room : translate('Кабинет не указан')}</td>
                      <td>{asset.responsible_person_name ?? '—'}</td>
                      <td>{asset.mol_name ?? '—'}</td>
                      <td>{formatMoney(asset.residual_cost ?? asset.residual_value)}</td>
                      <td>{ruVerification(asset.verification_status)}</td>
                      <td>{ruSource(asset.source)}</td>
                      <td>
                        <div className="analytics-actions">
                          <button type="button" className="ghost-button" onClick={() => setSelectedAssetId(asset.id)}>Детали</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('move', asset.id)}>Переместить</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('assign', asset.id)}>Закрепить</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('verify', asset.id)}>Проверить</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('dispose', asset.id)}>Списать</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-pagination">
              <p className="muted">Показано {assets.length} из {total}</p>
              <div className="analytics-actions">
                <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((v) => Math.max(1, v - 1))}>Назад</button>
                <span className="muted">Страница {page} / {totalPages}</span>
                <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((v) => Math.min(totalPages, v + 1))}>Вперед</button>
              </div>
            </div>
          </section>
        </>
      ) : null}

      {activeMode === 'cmdb' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card">
              <span>Классы CI</span>
              <strong>{ciClasses.length}</strong>
            </article>
            <article className="metric-card">
              <span>Опубликовано</span>
              <strong>{publishedClasses.length}</strong>
            </article>
            <article className="metric-card">
              <span>Наследуемые классы</span>
              <strong>{ciClasses.filter((entry) => entry.parent_class_id).length}</strong>
            </article>
            <article className="metric-card">
              <span>Атрибуты в схемах</span>
              <strong>{publishedClasses.reduce((sum, entry) => (
                sum + (entry.published_version?.effective_schema.fields.length ?? 0)
              ), 0)}</strong>
            </article>
          </section>

          {session?.user.role === 'saas_root' ? (
            <section className="foundation-card cmdb-tenant-context">
              <label className="inline-field">
                <span>Организация CMDB</span>
                <select
                  value={cmdbTenantId}
                  onChange={(event) => {
                    setCmdbTenantId(event.target.value)
                    setClassForm((current) => ({ ...current, parent_class_id: '' }))
                    setCiForm((current) => ({ ...current, ci_class_id: '' }))
                  }}
                >
                  <option value="">Выберите организацию</option>
                  {(tenantsQuery.data ?? []).map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
                  ))}
                </select>
              </label>
              <p className="muted">
                Классы, схемы и CI всегда создаются в явно выбранной организации.
              </p>
            </section>
          ) : null}

          <section className="section-card">
            <header className="section-header">
              <div>
                <p className="eyebrow">CI CLASS GOVERNANCE</p>
                <h3 className="section-title">Классы и версии схем</h3>
                <p className="section-subtitle">
                  Дочерняя версия фиксирует версию родителя. Уже созданные CI
                  сохраняют собственный schema hash и не меняются задним числом.
                </p>
              </div>
            </header>
            {ciClassesQuery.isPending ? <p className="loading-state">Загрузка классов…</p> : null}
            {!ciClassesQuery.isPending && ciClasses.length === 0 ? (
              <p className="empty-state">В выбранной организации классов пока нет.</p>
            ) : null}
            <div className="cmdb-class-grid">
              {ciClasses.map((ciClass) => {
                const version = ciClass.published_version ?? ciClass.draft_version
                return (
                  <article className="foundation-card cmdb-class-card" key={ciClass.id}>
                    <header>
                      <div>
                        <span className={`status-badge ${ciClass.status.toLowerCase()}`}>
                          {ciClass.status}
                        </span>
                        <strong>{ciClass.name}</strong>
                      </div>
                      <code>{ciClass.code}</code>
                    </header>
                    <p>{ciClass.description ?? 'Описание не задано.'}</p>
                    <dl>
                      <div><dt>Родитель</dt><dd>{ciClass.parent_class_name ?? 'Корневой класс'}</dd></div>
                      <div><dt>Версия</dt><dd>{version ? `v${version.version} · ${version.status}` : '—'}</dd></div>
                      <div><dt>Поля</dt><dd>{version?.effective_schema.fields.length ?? 0}</dd></div>
                      <div><dt>Schema hash</dt><dd><code>{version?.schema_hash.slice(0, 12) ?? '—'}</code></dd></div>
                    </dl>
                    {(version?.effective_schema.fields ?? []).length ? (
                      <div className="cmdb-field-chips">
                        {version?.effective_schema.fields.map((field) => (
                          <span key={field.key}>
                            {field.label} · {translate(fieldTypeLabels[field.type])}
                            {field.required ? ' *' : ''}
                            {field.inherited ? ' ↳' : ''}
                          </span>
                        ))}
                      </div>
                    ) : <p className="muted">Базовый класс без дополнительных полей.</p>}
                    {canManageCmdb(session) ? (
                      <div className="analytics-actions">
                        {ciClass.published_version && !ciClass.draft_version ? (
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => createClassDraftMutation.mutate(ciClass.id)}
                            disabled={createClassDraftMutation.isPending}
                          >
                            Новая версия
                          </button>
                        ) : null}
                        {ciClass.draft_version ? (
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => {
                              setEditingClassId(
                                editingClassId === ciClass.id ? null : ciClass.id,
                              )
                              setEditingClassFields(
                                ciClass.draft_version?.schema.fields ?? [],
                              )
                            }}
                          >
                            {editingClassId === ciClass.id ? 'Скрыть редактор' : 'Редактировать схему'}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    {editingClassId === ciClass.id && ciClass.draft_version ? (
                      <div className="cmdb-inline-editor">
                        <strong>Собственные поля draft v{ciClass.draft_version.version}</strong>
                        {editingClassFields.map((field, index) => (
                          <div className="cmdb-builder-field" key={`${field.key}-${index}`}>
                            <span>{field.label} · {translate(fieldTypeLabels[field.type])}{field.required ? ' *' : ''}</span>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => setEditingClassFields((current) => (
                                current.filter((_, fieldIndex) => fieldIndex !== index)
                              ))}
                            >
                              Удалить
                            </button>
                          </div>
                        ))}
                        <div className="cmdb-field-draft">
                          <input
                            aria-label={`${translate('Ключ нового поля')} ${ciClass.name}`}
                            value={editFieldDraft.key}
                            onChange={(event) => setEditFieldDraft((current) => ({
                              ...current,
                              key: event.target.value,
                            }))}
                            placeholder="monitoring_tier"
                          />
                          <input
                            aria-label={`${translate('Название нового поля')} ${ciClass.name}`}
                            value={editFieldDraft.label}
                            onChange={(event) => setEditFieldDraft((current) => ({
                              ...current,
                              label: event.target.value,
                            }))}
                            placeholder="Monitoring tier"
                          />
                          <select
                            aria-label={`${translate('Тип нового поля')} ${ciClass.name}`}
                            value={editFieldDraft.type}
                            onChange={(event) => setEditFieldDraft((current) => ({
                              ...current,
                              type: event.target.value as CIClassField['type'],
                            }))}
                          >
                            {Object.entries(fieldTypeLabels).map(([value, label]) => (
                              <option key={value} value={value}>{translate(label)}</option>
                            ))}
                          </select>
                          {['select', 'multiselect'].includes(editFieldDraft.type) ? (
                            <input
                              aria-label={`${translate('Варианты нового поля')} ${ciClass.name}`}
                              value={editFieldOptions}
                              onChange={(event) => setEditFieldOptions(event.target.value)}
                              placeholder="gold=Gold, silver=Silver"
                            />
                          ) : null}
                          <label className="checkbox-row">
                            <input
                              type="checkbox"
                              checked={editFieldDraft.required}
                              onChange={(event) => setEditFieldDraft((current) => ({
                                ...current,
                                required: event.target.checked,
                              }))}
                            />
                            Обязательное
                          </label>
                          <button type="button" className="ghost-button" onClick={addEditClassField}>
                            Добавить поле
                          </button>
                        </div>
                        {updateClassDraftMutation.isError ? (
                          <p className="form-error">{mutationError(updateClassDraftMutation.error)}</p>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => updateClassDraftMutation.mutate(ciClass.id)}
                          disabled={updateClassDraftMutation.isPending}
                        >
                          Сохранить схему
                        </button>
                      </div>
                    ) : null}
                    {ciClass.draft_version && canManageCmdb(session) ? (
                      <div className="cmdb-publish-row">
                        <input
                          aria-label={`${translate('Причина публикации')} ${ciClass.name}`}
                          value={publishReason[ciClass.id] ?? ''}
                          onChange={(event) => setPublishReason((current) => ({
                            ...current,
                            [ciClass.id]: event.target.value,
                          }))}
                          placeholder="Причина публикации"
                        />
                        <button
                          type="button"
                          onClick={() => publishClassMutation.mutate(ciClass.id)}
                          disabled={publishClassMutation.isPending}
                        >
                          Опубликовать
                        </button>
                      </div>
                    ) : null}
                  </article>
                )
              })}
            </div>
          </section>

          {canManageCmdb(session) ? (
            <div className="cmdb-admin-grid">
              <section className="section-card">
                <header className="section-header">
                  <div>
                    <h3 className="section-title">Новый класс CI</h3>
                    <p className="section-subtitle">Создаётся как черновик и требует публикации.</p>
                  </div>
                </header>
                <form
                  className="modal-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    createClassMutation.mutate()
                  }}
                >
                  <label>
                    <span>Родительский класс</span>
                    <select
                      value={classForm.parent_class_id}
                      onChange={(event) => setClassForm((current) => ({
                        ...current,
                        parent_class_id: event.target.value,
                      }))}
                    >
                      <option value="">Корневой класс</option>
                      {publishedClasses.map((entry) => (
                        <option key={entry.id} value={entry.id}>{entry.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Код</span>
                    <input
                      value={classForm.code}
                      onChange={(event) => setClassForm((current) => ({
                        ...current,
                        code: event.target.value,
                      }))}
                      placeholder="VIRTUAL_MACHINE"
                      required
                    />
                  </label>
                  <label>
                    <span>Название</span>
                    <input
                      value={classForm.name}
                      onChange={(event) => setClassForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }))}
                      placeholder="Виртуальная машина"
                      required
                    />
                  </label>
                  <label>
                    <span>Описание</span>
                    <textarea
                      value={classForm.description}
                      onChange={(event) => setClassForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))}
                    />
                  </label>

                  <div className="cmdb-field-builder">
                    <strong>Собственные поля класса</strong>
                    {classFields.map((field, index) => (
                      <div className="cmdb-builder-field" key={`${field.key}-${index}`}>
                        <span>{field.label} · {translate(fieldTypeLabels[field.type])}{field.required ? ' *' : ''}</span>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => setClassFields((current) => (
                            current.filter((_, fieldIndex) => fieldIndex !== index)
                          ))}
                        >
                          Удалить
                        </button>
                      </div>
                    ))}
                    <div className="cmdb-field-draft">
                      <input
                        aria-label="Ключ поля класса"
                        value={fieldDraft.key}
                        onChange={(event) => setFieldDraft((current) => ({
                          ...current,
                          key: event.target.value,
                        }))}
                        placeholder="hostname"
                      />
                      <input
                        aria-label="Название поля класса"
                        value={fieldDraft.label}
                        onChange={(event) => setFieldDraft((current) => ({
                          ...current,
                          label: event.target.value,
                        }))}
                        placeholder="Hostname"
                      />
                      <select
                        aria-label="Тип поля класса"
                        value={fieldDraft.type}
                        onChange={(event) => setFieldDraft((current) => ({
                          ...current,
                          type: event.target.value as CIClassField['type'],
                        }))}
                      >
                        {Object.entries(fieldTypeLabels).map(([value, label]) => (
                          <option key={value} value={value}>{translate(label)}</option>
                        ))}
                      </select>
                      {['select', 'multiselect'].includes(fieldDraft.type) ? (
                        <input
                          aria-label="Варианты поля класса"
                          value={fieldOptions}
                          onChange={(event) => setFieldOptions(event.target.value)}
                          placeholder="linux=Linux, windows=Windows"
                        />
                      ) : null}
                      <label className="checkbox-row">
                        <input
                          type="checkbox"
                          checked={fieldDraft.required}
                          onChange={(event) => setFieldDraft((current) => ({
                            ...current,
                            required: event.target.checked,
                          }))}
                        />
                        Обязательное
                      </label>
                      <button type="button" className="ghost-button" onClick={addClassField}>
                        Добавить поле
                      </button>
                    </div>
                  </div>
                  {createClassMutation.isError ? (
                    <p className="form-error">{mutationError(createClassMutation.error)}</p>
                  ) : null}
                  <button
                    type="submit"
                    disabled={
                      createClassMutation.isPending
                      || !classForm.code.trim()
                      || !classForm.name.trim()
                      || (session?.user.role === 'saas_root' && !cmdbTenantId)
                    }
                  >
                    Создать черновик класса
                  </button>
                </form>
              </section>

              <section className="section-card">
                <header className="section-header">
                  <div>
                    <h3 className="section-title">Новая конфигурационная единица</h3>
                    <p className="section-subtitle">CI получает неизменяемый снимок опубликованной схемы.</p>
                  </div>
                </header>
                <form
                  className="modal-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    createCiMutation.mutate()
                  }}
                >
                  <label>
                    <span>Класс CI</span>
                    <select
                      value={ciForm.ci_class_id}
                      onChange={(event) => {
                        setCiForm((current) => ({
                          ...current,
                          ci_class_id: event.target.value,
                        }))
                        setCiAttributes({})
                      }}
                      required
                    >
                      <option value="">Выберите класс</option>
                      {publishedClasses.map((entry) => (
                        <option key={entry.id} value={entry.id}>{entry.name}</option>
                      ))}
                    </select>
                  </label>
                  <label><span>Asset tag</span><input value={ciForm.asset_tag} onChange={(event) => setCiForm((current) => ({ ...current, asset_tag: event.target.value }))} placeholder="CI-APP-001" required /></label>
                  <label><span>Название</span><input value={ciForm.name} onChange={(event) => setCiForm((current) => ({ ...current, name: event.target.value }))} placeholder="itsm-app-01" required /></label>
                  <label><span>Инвентарный номер</span><input value={ciForm.inventory_number} onChange={(event) => setCiForm((current) => ({ ...current, inventory_number: event.target.value }))} /></label>
                  <label><span>Серийный номер</span><input value={ciForm.serial_number} onChange={(event) => setCiForm((current) => ({ ...current, serial_number: event.target.value }))} /></label>
                  <label><span>Support group</span><input value={ciForm.support_group} onChange={(event) => setCiForm((current) => ({ ...current, support_group: event.target.value }))} /></label>
                  <label>
                    <span>Lifecycle</span>
                    <select value={ciForm.lifecycle_status} onChange={(event) => setCiForm((current) => ({ ...current, lifecycle_status: event.target.value as typeof current.lifecycle_status }))}>
                      {['PLANNING', 'ORDERED', 'IN_STOCK', 'ACTIVE', 'MAINTENANCE', 'RETIRED', 'DISPOSED'].map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>Критичность</span>
                    <select value={ciForm.criticality} onChange={(event) => setCiForm((current) => ({ ...current, criticality: event.target.value as Asset['criticality'] }))}>
                      {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>Среда</span>
                    <select value={ciForm.environment} onChange={(event) => setCiForm((current) => ({ ...current, environment: event.target.value as Asset['environment'] }))}>
                      {['PRODUCTION', 'STAGING', 'TEST', 'DEVELOPMENT', 'OTHER'].map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                  <label><span>Локация</span><input value={ciForm.location} onChange={(event) => setCiForm((current) => ({ ...current, location: event.target.value }))} required /></label>

                  {(selectedCiClass?.published_version?.effective_schema.fields ?? []).map((field) => (
                    <label key={field.key}>
                      <span>{field.label}{field.required ? ' *' : ''}{field.inherited ? ' · inherited' : ''}</span>
                      {field.type === 'boolean' ? (
                        <input
                          type="checkbox"
                          checked={Boolean(ciAttributes[field.key])}
                          onChange={(event) => updateCiAttribute(field, event.target.checked)}
                        />
                      ) : field.type === 'select' ? (
                        <select
                          value={String(ciAttributes[field.key] ?? '')}
                          onChange={(event) => updateCiAttribute(field, event.target.value)}
                          required={field.required}
                        >
                          <option value="">Выберите</option>
                          {field.options.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                      ) : field.type === 'multiselect' ? (
                        <input
                          value={Array.isArray(ciAttributes[field.key]) ? (ciAttributes[field.key] as string[]).join(', ') : ''}
                          onChange={(event) => setCiAttributes((current) => ({
                            ...current,
                            [field.key]: event.target.value.split(',').map((entry) => entry.trim()).filter(Boolean),
                          }))}
                          placeholder={field.options.map((option) => option.value).join(', ')}
                          required={field.required}
                        />
                      ) : field.type === 'textarea' ? (
                        <textarea
                          value={String(ciAttributes[field.key] ?? '')}
                          onChange={(event) => updateCiAttribute(field, event.target.value)}
                          required={field.required}
                        />
                      ) : (
                        <input
                          type={
                            field.type === 'integer' || field.type === 'number'
                              ? 'number'
                              : field.type === 'date'
                                ? 'date'
                                : field.type === 'datetime'
                                  ? 'datetime-local'
                                  : field.type === 'email'
                                    ? 'email'
                                    : 'text'
                          }
                          value={String(ciAttributes[field.key] ?? '')}
                          onChange={(event) => updateCiAttribute(field, event.target.value)}
                          required={field.required}
                        />
                      )}
                    </label>
                  ))}
                  {createCiMutation.isError ? (
                    <p className="form-error">{mutationError(createCiMutation.error)}</p>
                  ) : null}
                  {createCiMutation.isSuccess ? (
                    <p className="form-success">CI создан и добавлен в реестр.</p>
                  ) : null}
                  <button
                    type="submit"
                    disabled={
                      createCiMutation.isPending
                      || !ciForm.ci_class_id
                      || !ciForm.asset_tag.trim()
                      || !ciForm.name.trim()
                    }
                  >
                    Создать CI
                  </button>
                </form>
              </section>
            </div>
          ) : null}
        </>
      ) : null}

      {activeMode === 'topology' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card">
              <span>CI в модели</span>
              <strong>{configurationItems.length}</strong>
            </article>
            <article className="metric-card">
              <span>Типы связей</span>
              <strong>{relationshipTypes.length}</strong>
            </article>
            <article className="metric-card">
              <span>Узлы на карте</span>
              <strong>{topology?.nodes.length ?? 0}</strong>
            </article>
            <article className="metric-card">
              <span>Связи на карте</span>
              <strong>{topology?.edges.length ?? 0}</strong>
            </article>
          </section>

          {session?.user.role === 'saas_root' ? (
            <section className="foundation-card cmdb-tenant-context">
              <label className="inline-field">
                <span>Организация service model</span>
                <select
                  value={cmdbTenantId}
                  onChange={(event) => {
                    setCmdbTenantId(event.target.value)
                    setTopologyRootId('')
                    setRelationshipForm({
                      relationship_type_id: '',
                      source_ci_id: '',
                      target_ci_id: '',
                      description: '',
                    })
                  }}
                >
                  <option value="">Выберите организацию</option>
                  {(tenantsQuery.data ?? []).map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
                  ))}
                </select>
              </label>
              <p className="muted">
                Карта и связи загружаются только для явно выбранного tenant.
              </p>
            </section>
          ) : null}

          <section className="section-card">
            <header className="section-header">
              <div>
                <p className="eyebrow">SERVICE TOPOLOGY</p>
                <h3 className="section-title">Карта зависимостей сервисов и CI</h3>
                <p className="section-subtitle">
                  Направление связи фиксировано типом. Глубина ограничивает
                  traversal, а tenant isolation применяется на каждом ребре.
                </p>
              </div>
            </header>
            <div className="cmdb-topology-controls">
              <label className="inline-field">
                <span>Корневой CI</span>
                <select
                  value={topologyRootId}
                  onChange={(event) => setTopologyRootId(event.target.value)}
                >
                  <option value="">Выберите CI</option>
                  {configurationItems.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {item.ci_class_name ?? item.ci_class_code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline-field">
                <span>Направление</span>
                <select
                  value={topologyDirection}
                  onChange={(event) => setTopologyDirection(
                    event.target.value as typeof topologyDirection,
                  )}
                >
                  <option value="both">Оба направления</option>
                  <option value="downstream">Downstream</option>
                  <option value="upstream">Upstream</option>
                </select>
              </label>
              <label className="inline-field">
                <span>Глубина</span>
                <select
                  value={String(topologyDepth)}
                  onChange={(event) => setTopologyDepth(Number(event.target.value))}
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8].map((value) => (
                    <option key={value} value={value}>{value}</option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={!topologyRootId || topologyQuery.isFetching}
                onClick={() => topologyQuery.refetch()}
              >
                Обновить карту
              </button>
            </div>
            {configurationItemsQuery.isPending || topologyQuery.isPending ? (
              <p className="loading-state">Построение service topology…</p>
            ) : null}
            {configurationItemsQuery.isError ? (
              <p className="form-error">
                {mutationError(configurationItemsQuery.error)}
              </p>
            ) : null}
            {topologyQuery.isError ? (
              <p className="form-error">{mutationError(topologyQuery.error)}</p>
            ) : null}
            {!configurationItemsQuery.isPending && configurationItems.length === 0 ? (
              <p className="empty-state">
                Сначала создайте CI в опубликованных классах CMDB.
              </p>
            ) : null}
            {topology ? (
              <>
                {topology.truncated ? (
                  <p className="form-error">
                    Карта ограничена 300 узлами. Выберите меньшую глубину или
                    более точный корневой CI.
                  </p>
                ) : null}
                <div className="cmdb-topology-board">
                  {Array.from(
                    new Set(topology.nodes.map((node) => node.depth ?? 0)),
                  ).sort((left, right) => left - right).map((layerDepth) => (
                    <section className="cmdb-topology-layer" key={layerDepth}>
                      <header>
                        <span>Уровень {layerDepth}</span>
                        <strong>
                          {topology.nodes.filter(
                            (node) => (node.depth ?? 0) === layerDepth,
                          ).length}
                        </strong>
                      </header>
                      {topology.nodes.filter(
                        (node) => (node.depth ?? 0) === layerDepth,
                      ).map((node) => (
                        <button
                          type="button"
                          className={`cmdb-topology-node ${
                            node.id === topology.root_ci_id ? 'root' : ''
                          }`}
                          key={node.id}
                          onClick={() => setTopologyRootId(node.id)}
                        >
                          <span>{node.ci_class_name ?? node.ci_class_code ?? 'CI'}</span>
                          <strong>{node.name}</strong>
                          <small>{node.asset_tag}</small>
                          <small>
                            {node.environment} · {node.criticality}
                          </small>
                        </button>
                      ))}
                    </section>
                  ))}
                </div>
              </>
            ) : null}
          </section>

          <section className="section-card">
            <header className="section-header">
              <div>
                <h3 className="section-title">Рёбра service model</h3>
                <p className="section-subtitle">
                  Forward и reverse labels показывают смысл связи в обоих
                  направлениях. Удаление выполняется как контролируемый retire.
                </p>
              </div>
            </header>
            <div className="cmdb-relationship-list">
              {(topology?.edges ?? []).map((edge) => (
                <article className="foundation-card cmdb-relationship-card" key={edge.id}>
                  <div className="cmdb-relationship-path">
                    <strong>{edge.source.name}</strong>
                    <span>
                      {edge.forward_label}
                      <code>{edge.relationship_type_code}</code>
                    </span>
                    <strong>{edge.target.name}</strong>
                  </div>
                  <p className="muted">
                    Обратно: {edge.target.name} {edge.reverse_label}{' '}
                    {edge.source.name}
                  </p>
                  {edge.description ? <p>{edge.description}</p> : null}
                  {canManageCmdb(session) ? (
                    <div className="cmdb-retire-row">
                      <input
                        value={retireReason[edge.id] ?? ''}
                        onChange={(event) => setRetireReason((current) => ({
                          ...current,
                          [edge.id]: event.target.value,
                        }))}
                        placeholder="Причина вывода связи"
                      />
                      <button
                        type="button"
                        className="ghost-button danger"
                        disabled={retireRelationshipMutation.isPending}
                        onClick={() => retireRelationshipMutation.mutate(edge.id)}
                      >
                        Вывести связь
                      </button>
                    </div>
                  ) : null}
                </article>
              ))}
              {topology && topology.edges.length === 0 ? (
                <p className="empty-state">
                  Для выбранного CI в этой глубине активных связей нет.
                </p>
              ) : null}
            </div>
            {retireRelationshipMutation.isError ? (
              <p className="form-error">
                {mutationError(retireRelationshipMutation.error)}
              </p>
            ) : null}
          </section>

          {canManageCmdb(session) ? (
            <div className="cmdb-admin-grid">
              <section className="section-card">
                <header className="section-header">
                  <div>
                    <h3 className="section-title">Новая связь CI</h3>
                    <p className="section-subtitle">
                      API проверит классы, cardinality, tenant и недопустимые циклы.
                    </p>
                  </div>
                </header>
                <form
                  className="modal-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    createRelationshipMutation.mutate()
                  }}
                >
                  <label>
                    <span>Тип связи</span>
                    <select
                      value={relationshipForm.relationship_type_id}
                      onChange={(event) => setRelationshipForm((current) => ({
                        ...current,
                        relationship_type_id: event.target.value,
                      }))}
                      required
                    >
                      <option value="">Выберите тип</option>
                      {activeRelationshipTypes.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name} · {item.source_class_name ?? 'любой CI'}
                          {' → '}
                          {item.target_class_name ?? 'любой CI'}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Source CI</span>
                    <select
                      value={relationshipForm.source_ci_id}
                      onChange={(event) => setRelationshipForm((current) => ({
                        ...current,
                        source_ci_id: event.target.value,
                      }))}
                      required
                    >
                      <option value="">Выберите source</option>
                      {configurationItems.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name} · {item.ci_class_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Target CI</span>
                    <select
                      value={relationshipForm.target_ci_id}
                      onChange={(event) => setRelationshipForm((current) => ({
                        ...current,
                        target_ci_id: event.target.value,
                      }))}
                      required
                    >
                      <option value="">Выберите target</option>
                      {configurationItems.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name} · {item.ci_class_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Описание</span>
                    <textarea
                      value={relationshipForm.description}
                      onChange={(event) => setRelationshipForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))}
                    />
                  </label>
                  {createRelationshipMutation.isError ? (
                    <p className="form-error">
                      {mutationError(createRelationshipMutation.error)}
                    </p>
                  ) : null}
                  {createRelationshipMutation.isSuccess ? (
                    <p className="form-success">
                      Связь добавлена и карта перестроена.
                    </p>
                  ) : null}
                  <button
                    type="submit"
                    disabled={
                      createRelationshipMutation.isPending
                      || !relationshipForm.relationship_type_id
                      || !relationshipForm.source_ci_id
                      || !relationshipForm.target_ci_id
                      || relationshipForm.source_ci_id
                        === relationshipForm.target_ci_id
                    }
                  >
                    Создать связь
                  </button>
                </form>
              </section>

              <section className="section-card">
                <header className="section-header">
                  <div>
                    <h3 className="section-title">Новый тип связи</h3>
                    <p className="section-subtitle">
                      Ограничения классов наследуются: дочерний класс допустим
                      там, где указан его родитель.
                    </p>
                  </div>
                </header>
                <form
                  className="modal-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    createRelationshipTypeMutation.mutate()
                  }}
                >
                  <label>
                    <span>Код</span>
                    <input
                      value={relationshipTypeForm.code}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        code: event.target.value,
                      }))}
                      placeholder="DATABASE_DEPENDS_ON"
                      required
                    />
                  </label>
                  <label>
                    <span>Название</span>
                    <input
                      value={relationshipTypeForm.name}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }))}
                      required
                    />
                  </label>
                  <label>
                    <span>Forward label</span>
                    <input
                      value={relationshipTypeForm.forward_label}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        forward_label: event.target.value,
                      }))}
                      placeholder="зависит от"
                      required
                    />
                  </label>
                  <label>
                    <span>Reverse label</span>
                    <input
                      value={relationshipTypeForm.reverse_label}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        reverse_label: event.target.value,
                      }))}
                      placeholder="поддерживает"
                      required
                    />
                  </label>
                  <label>
                    <span>Source class</span>
                    <select
                      value={relationshipTypeForm.source_class_id}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        source_class_id: event.target.value,
                      }))}
                    >
                      <option value="">Любой класс</option>
                      {publishedClasses.map((item) => (
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Target class</span>
                    <select
                      value={relationshipTypeForm.target_class_id}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        target_class_id: event.target.value,
                      }))}
                    >
                      <option value="">Любой класс</option>
                      {publishedClasses.map((item) => (
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </select>
                  </label>
                  <div className="cmdb-cardinality-grid">
                    <label>
                      <span>Targets per source</span>
                      <select
                        value={relationshipTypeForm.source_cardinality}
                        onChange={(event) => setRelationshipTypeForm((current) => ({
                          ...current,
                          source_cardinality: event.target.value as 'ONE' | 'MANY',
                        }))}
                      >
                        <option value="ONE">ONE</option>
                        <option value="MANY">MANY</option>
                      </select>
                    </label>
                    <label>
                      <span>Sources per target</span>
                      <select
                        value={relationshipTypeForm.target_cardinality}
                        onChange={(event) => setRelationshipTypeForm((current) => ({
                          ...current,
                          target_cardinality: event.target.value as 'ONE' | 'MANY',
                        }))}
                      >
                        <option value="ONE">ONE</option>
                        <option value="MANY">MANY</option>
                      </select>
                    </label>
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={relationshipTypeForm.allow_cycles}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        allow_cycles: event.target.checked,
                      }))}
                    />
                    Разрешить циклы
                  </label>
                  <label>
                    <span>Описание</span>
                    <textarea
                      value={relationshipTypeForm.description}
                      onChange={(event) => setRelationshipTypeForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))}
                    />
                  </label>
                  {createRelationshipTypeMutation.isError ? (
                    <p className="form-error">
                      {mutationError(createRelationshipTypeMutation.error)}
                    </p>
                  ) : null}
                  <button
                    type="submit"
                    disabled={
                      createRelationshipTypeMutation.isPending
                      || !relationshipTypeForm.code.trim()
                      || !relationshipTypeForm.name.trim()
                      || !relationshipTypeForm.forward_label.trim()
                      || !relationshipTypeForm.reverse_label.trim()
                      || (session?.user.role === 'saas_root' && !cmdbTenantId)
                    }
                  >
                    Создать тип связи
                  </button>
                </form>
              </section>
            </div>
          ) : null}

          <section className="section-card">
            <header className="section-header">
              <div>
                <h3 className="section-title">Политики типов связей</h3>
                <p className="section-subtitle">
                  Стандартная migration создаёт цепочку Business Service →
                  Technical Service → Application → Infrastructure и размещение.
                </p>
              </div>
            </header>
            <div className="cmdb-relationship-type-grid">
              {relationshipTypes.map((item) => (
                <article className="foundation-card" key={item.id}>
                  <header className="cmdb-type-header">
                    <span className={`status-badge ${item.status.toLowerCase()}`}>
                      {item.status}
                    </span>
                    <code>{item.code}</code>
                  </header>
                  <strong>{item.name}</strong>
                  <p>
                    {item.source_class_name ?? 'Любой CI'}{' '}
                    <span className="cmdb-arrow">→</span>{' '}
                    {item.target_class_name ?? 'Любой CI'}
                  </p>
                  <dl>
                    <div>
                      <dt>Cardinality</dt>
                      <dd>{item.source_cardinality} : {item.target_cardinality}</dd>
                    </div>
                    <div>
                      <dt>Cycles</dt>
                      <dd>{item.allow_cycles ? 'allowed' : 'blocked'}</dd>
                    </div>
                    <div>
                      <dt>Active edges</dt>
                      <dd>{item.active_relationships}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}

      {activeMode === 'reconciliation' ? (
        <CMDBReconciliationPanel
          accessToken={session?.access_token ?? ''}
          tenantId={cmdbTenantId}
          isRoot={session?.user.role === 'saas_root'}
          canManage={canManageCmdb(session)}
          tenants={tenantsQuery.data ?? []}
          classes={ciClasses}
          onTenantChange={setCmdbTenantId}
        />
      ) : null}

      {activeMode === 'discovery' ? (
        <AssetDiscoveryPanel
          accessToken={session?.access_token ?? ''}
          tenantId={cmdbTenantId}
          isRoot={session?.user.role === 'saas_root'}
          canManage={session?.user.role === 'saas_root' || Boolean(session?.user.permissions.includes('asset.discovery.manage'))}
          canRun={session?.user.role === 'saas_root' || Boolean(session?.user.permissions.includes('asset.discovery.run'))}
          canReview={session?.user.role === 'saas_root' || Boolean(session?.user.permissions.includes('asset.discovery.review'))}
          tenants={tenantsQuery.data ?? []}
          classes={ciClasses}
          onTenantChange={setCmdbTenantId}
        />
      ) : null}

      {activeMode === 'quality' ? (
        <>
          {session?.user.role === 'saas_root' ? (
            <section className="section-card cmdb-tenant-selector">
              <label>
                Организация
                <select value={cmdbTenantId} onChange={(event) => setCmdbTenantId(event.target.value)}>
                  <option value="">Выберите организацию</option>
                  {(tenantsQuery.data ?? []).map((tenant) => <option value={tenant.id} key={tenant.id}>{tenant.name}</option>)}
                </select>
              </label>
            </section>
          ) : null}
          {session?.user.role !== 'saas_root' || cmdbTenantId ? (
            <CMDBQualityPanel
              accessToken={session?.access_token ?? ''}
              tenantId={session?.user.role === 'saas_root' ? cmdbTenantId : undefined}
              currentUserId={session?.user.role === 'saas_root' ? undefined : session?.user.id}
              canScan={canVerifyCmdb(session)}
              canManage={canManageCmdb(session)}
            />
          ) : (
            <p className="empty-state">Выберите организацию для анализа качества CMDB.</p>
          )}
        </>
      ) : null}

      {activeMode === 'inventory' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card"><span>Всего активов</span><strong>{assets.length}</strong></article>
            <article className="metric-card"><span>Проверено</span><strong>{inventoryStats.verified}</strong></article>
            <article className="metric-card"><span>Требует кабинета</span><strong>{inventoryStats.needsLocation}</strong></article>
            <article className="metric-card"><span>Требует проверки</span><strong>{inventoryStats.needsVerification}</strong></article>
            <article className="metric-card"><span>Списано</span><strong>{inventoryStats.disposed}</strong></article>
            <article className="metric-card"><span>Импорт Excel</span><strong>{inventoryStats.excel}</strong></article>
            <article className="metric-card"><span>Активы без МОЛ</span><strong>{inventoryStats.withoutMol}</strong></article>
            <article className="metric-card"><span>Активы без кабинета</span><strong>{inventoryStats.withoutRoom}</strong></article>
          </section>
          <section className="section-card">
            <header className="section-header"><h3 className="section-title">Быстрые фильтры</h3></header>
            <div className="analytics-actions">
              <button type="button" className="ghost-button" onClick={() => { setRoomFilter('Кабинет не указан'); setActiveMode('registry') }}>Требует кабинета</button>
              <button type="button" className="ghost-button" onClick={() => { setVerificationFilter('pending'); setActiveMode('registry') }}>Требует проверки</button>
              <button type="button" className="ghost-button" onClick={() => { setMolFilter('ALL'); setActiveMode('registry') }}>Без МОЛ</button>
              <button type="button" className="ghost-button" onClick={() => { setStatusFilter('disposed'); setActiveMode('registry') }}>Списанные</button>
              <button type="button" className="ghost-button" onClick={() => { setSourceFilter('excel_import'); setActiveMode('registry') }}>Импорт Excel</button>
            </div>
          </section>
        </>
      ) : null}

      {activeMode === 'rooms' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Группировка по кабинетам</h3></header>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Кабинет</th><th>Количество активов</th><th>Ответственные</th><th>Типы оборудования</th><th>Требует проверки</th><th>Действие</th></tr></thead>
              <tbody>
                {roomsGroups.map((item) => (
                  <tr key={item.room}>
                    <td>{item.room}</td>
                    <td>{item.count}</td>
                    <td>{item.responsibles}</td>
                    <td>{item.types || '—'}</td>
                    <td>{item.needsVerification}</td>
                    <td><button type="button" className="ghost-button" onClick={() => { setRoomFilter(item.room); setActiveMode('registry') }}>Показать активы</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'responsible' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Группировка по ответственным</h3></header>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Ответственный</th><th>Подразделение</th><th>Количество активов</th><th>Общая остаточная стоимость</th><th>Активы без кабинета</th><th>Списанные</th><th>Действие</th></tr></thead>
              <tbody>
                {responsibleGroups.map((item) => (
                  <tr key={item.responsible}>
                    <td>{item.responsible}</td>
                    <td>{item.department}</td>
                    <td>{item.count}</td>
                    <td>{formatMoney(item.residual)}</td>
                    <td>{item.withoutRoom}</td>
                    <td>{item.disposed}</td>
                    <td><button type="button" className="ghost-button" onClick={() => { setResponsibleFilter(item.responsible); setActiveMode('registry') }}>Показать активы</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'disposal' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Списанные активы</h3></header>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Инв. №</th><th>Наименование</th><th>Дата списания</th><th>Причина</th><th>Остаточная стоимость</th><th>Ответственный</th><th>Действие</th></tr></thead>
              <tbody>
                {disposedAssets.map((asset) => (
                  <tr key={asset.id}>
                    <td>{asset.inventory_number ?? asset.asset_tag}</td>
                    <td>{asset.name}</td>
                    <td>{formatDate(asset.writeoff_date ?? asset.disposed_at)}</td>
                    <td>{asset.writeoff_reason ?? '—'}</td>
                    <td>{formatMoney(asset.residual_cost ?? asset.residual_value)}</td>
                    <td>{asset.responsible_person_name ?? '—'}</td>
                    <td><button type="button" className="ghost-button" onClick={() => openActionModal('restore', asset.id)}>Восстановить</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'history' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">История активов</h3></header>
          <div className="table-filters" style={{ gridTemplateColumns: 'repeat(5, minmax(0,1fr))' }}>
            <label className="inline-field"><span>action</span><select value={historyAction} onChange={(event) => setHistoryAction(event.target.value)}><option value="ALL">Все</option><option value="asset_updated">asset_updated</option><option value="asset_moved">asset_moved</option><option value="asset_assigned">asset_assigned</option><option value="asset_verified">asset_verified</option><option value="asset_disposed">asset_disposed</option><option value="asset_restored">asset_restored</option></select></label>
            <label className="inline-field"><span>actor</span><input value={historyActor} onChange={(event) => setHistoryActor(event.target.value)} placeholder="email или ФИО" /></label>
            <label className="inline-field"><span>asset</span><input value={historyAsset} onChange={(event) => setHistoryAsset(event.target.value)} placeholder="имя/инв.№" /></label>
            <label className="inline-field"><span>date_from</span><input type="date" value={historyDateFrom} onChange={(event) => setHistoryDateFrom(event.target.value)} /></label>
            <label className="inline-field"><span>date_to</span><input type="date" value={historyDateTo} onChange={(event) => setHistoryDateTo(event.target.value)} /></label>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Дата</th><th>Action</th><th>Asset</th><th>Actor</th><th>Комментарий</th></tr></thead>
              <tbody>
                {historyFeedQuery.isPending ? <tr><td colSpan={5}><p className="loading-state">Загрузка данных...</p></td></tr> : null}
                {!historyFeedQuery.isPending && historyFeed.length === 0 ? <tr><td colSpan={5}><p className="empty-state">Данных пока нет.</p></td></tr> : null}
                {historyFeed.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.action}</td>
                    <td>{item.asset_name ?? '—'} · {item.inventory_number ?? '—'}</td>
                    <td>{item.actor_email ?? '—'}</td>
                    <td>{item.comment ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'import' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Импорт Excel</h3><p className="section-subtitle">Upload → preview → commit. Существующие импортированные активы не удаляются.</p></header>
          <div className="analytics-actions">
            <input type="file" accept=".xlsx" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
            <button type="button" onClick={async () => {
              if (!selectedFile) return
              const batch = await uploadMutation.mutateAsync(selectedFile)
              await previewMutation.mutateAsync(batch.id)
            }} disabled={!selectedFile || uploadMutation.isPending || previewMutation.isPending}>Загрузить и проверить</button>
            <button type="button" className="ghost-button" onClick={() => { if (activeBatchId) previewMutation.mutate(activeBatchId) }} disabled={!activeBatchId || previewMutation.isPending}>Обновить preview</button>
            <button type="button" className="ghost-button" onClick={() => { if (activeBatchId) commitMutation.mutate(activeBatchId) }} disabled={!activeBatchId || commitMutation.isPending}>Импортировать валидные</button>
          </div>
          <p className="muted">Batch: {activeBatchId ?? '—'} · Статус: {activeBatch?.status ?? '—'}</p>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Строка</th><th>Инв. №</th><th>Наименование</th><th>Статус</th><th>Ошибка</th></tr></thead>
              <tbody>
                {(rowsQuery.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>{row.row_number}</td>
                    <td>{String(row.normalized.inventory_number ?? '—')}</td>
                    <td>{String(row.normalized.name ?? '—')}</td>
                    <td>{row.status}</td>
                    <td>{row.error_message ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {selectedAssetId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeDetail}>
          <section
            ref={detailDialogRef}
            className="modal-card modal-card-xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="asset-detail-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">КАРТОЧКА ОБОРУДОВАНИЯ</p>
                <h2 id="asset-detail-dialog-title">{selectedAsset?.name ?? 'Загрузка...'}</h2>
                <p className="modal-subtitle">{selectedAsset?.inventory_number ?? selectedAsset?.asset_tag ?? '—'} · {ruStatus(selectedAsset?.status)}</p>
              </div>
              <button type="button" className="ghost-button" onClick={closeDetail}>Закрыть</button>
            </div>

            <nav className="module-subnav">
              <button type="button" className={`module-subnav-tab ${detailTab === 'overview' ? 'active' : ''}`} onClick={() => setDetailTab('overview')}>Обзор</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'accounting' ? 'active' : ''}`} onClick={() => setDetailTab('accounting')}>Учёт</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'location' ? 'active' : ''}`} onClick={() => setDetailTab('location')}>Локация</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'responsible' ? 'active' : ''}`} onClick={() => setDetailTab('responsible')}>Ответственные</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'relationships' ? 'active' : ''}`} onClick={() => setDetailTab('relationships')}>Связи CI</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'impact' ? 'active' : ''}`} onClick={() => setDetailTab('impact')}>Влияние</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'governance' ? 'active' : ''}`} onClick={() => setDetailTab('governance')}>Владение полями</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'tickets' ? 'active' : ''}`} onClick={() => setDetailTab('tickets')}>Заявки</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'history' ? 'active' : ''}`} onClick={() => setDetailTab('history')}>История</button>
            </nav>

            {detailTab === 'overview' ? (
              <>
                <div className="detail-fields">
                  <div><span>Класс CI</span><strong>{selectedAsset?.ci_class_name ?? selectedAsset?.asset_type ?? '—'}</strong></div>
                  <div><span>Версия схемы</span><strong>{selectedAsset?.ci_schema_version ? `v${selectedAsset.ci_schema_version}` : '—'}</strong></div>
                  <div><span>Schema hash</span><strong><code>{selectedAsset?.ci_schema_hash?.slice(0, 16) ?? '—'}</code></strong></div>
                  <div><span>Lifecycle</span><strong>{selectedAsset?.lifecycle_status ?? ruStatus(selectedAsset?.status)}</strong></div>
                  <div><span>Критичность</span><strong>{selectedAsset?.criticality ?? '—'}</strong></div>
                  <div><span>Среда</span><strong>{selectedAsset?.environment ?? '—'}</strong></div>
                  <div><span>Support group</span><strong>{selectedAsset?.support_group ?? '—'}</strong></div>
                  <div><span>CI version</span><strong>{selectedAsset?.ci_version ?? '—'}</strong></div>
                  <div><span>Источник</span><strong>{ruSource(selectedAsset?.source)}</strong></div>
                  <div><span>Дата импорта</span><strong>{formatDateTime(selectedAsset?.imported_at)}</strong></div>
                  <div><span>notes</span><strong>{selectedAsset?.notes ?? selectedAsset?.description ?? '—'}</strong></div>
                </div>
                {Object.keys(selectedAsset?.ci_attributes ?? {}).length ? (
                  <section className="cmdb-attributes">
                    <h3>Атрибуты класса</h3>
                    <div className="detail-fields">
                      {Object.entries(selectedAsset?.ci_attributes ?? {}).map(([key, value]) => (
                        <div key={key}><span>{key}</span><strong>{Array.isArray(value) ? value.join(', ') : String(value)}</strong></div>
                      ))}
                    </div>
                  </section>
                ) : null}
                {selectedAsset ? (
                  <EntityCustomFieldsPanel
                    entityType="asset"
                    entityId={selectedAsset.id}
                    tenantId={selectedAsset.tenant_id}
                  />
                ) : null}
              </>
            ) : null}

            {detailTab === 'accounting' ? (
              <div className="detail-fields">
                <div><span>purchase_date</span><strong>{formatDate(selectedAsset?.purchase_date)}</strong></div>
                <div><span>purchase_year</span><strong>{selectedAsset?.purchase_year ?? '—'}</strong></div>
                <div><span>initial_cost</span><strong>{formatMoney(selectedAsset?.initial_cost)}</strong></div>
                <div><span>depreciation_amount</span><strong>{formatMoney(selectedAsset?.depreciation_amount)}</strong></div>
                <div><span>residual_cost</span><strong>{formatMoney(selectedAsset?.residual_cost ?? selectedAsset?.residual_value)}</strong></div>
                <div><span>writeoff</span><strong>{formatDate(selectedAsset?.writeoff_date)} · {selectedAsset?.writeoff_reason ?? '—'}</strong></div>
              </div>
            ) : null}

            {detailTab === 'location' ? (
              <div className="detail-fields">
                <div><span>building</span><strong>{selectedAsset?.building ?? '—'}</strong></div>
                <div><span>floor</span><strong>{selectedAsset?.floor ?? '—'}</strong></div>
                <div><span>room</span><strong>{selectedAsset?.room ?? 'Кабинет не указан'}</strong></div>
                <div><span>location_label</span><strong>{selectedAsset?.location_label ?? '—'}</strong></div>
                <div><span>location_verified_at</span><strong>{formatDateTime(selectedAsset?.location_verified_at)}</strong></div>
              </div>
            ) : null}

            {detailTab === 'responsible' ? (
              <div className="detail-fields">
                <div><span>responsible_person_name</span><strong>{selectedAsset?.responsible_person_name ?? '—'}</strong></div>
                <div><span>responsible_department</span><strong>{selectedAsset?.responsible_department ?? '—'}</strong></div>
                <div><span>mol_name</span><strong>{selectedAsset?.mol_name ?? '—'}</strong></div>
                <div><span>mol_department</span><strong>{selectedAsset?.mol_department ?? '—'}</strong></div>
              </div>
            ) : null}

            {detailTab === 'relationships' ? (
              <div className="activity-list">
                {!selectedAsset?.ci_class_id ? (
                  <p className="empty-state">
                    Актив ещё не классифицирован как CI.
                  </p>
                ) : null}
                {detailTopologyQuery.isPending ? (
                  <p className="loading-state">Загрузка связей CI…</p>
                ) : null}
                {detailTopologyQuery.isError ? (
                  <p className="form-error">
                    {mutationError(detailTopologyQuery.error)}
                  </p>
                ) : null}
                {selectedAsset?.ci_class_id
                  && !detailTopologyQuery.isPending
                  && (detailTopologyQuery.data?.edges.length ?? 0) === 0 ? (
                    <p className="empty-state">
                      У CI пока нет активных входящих или исходящих связей.
                    </p>
                  ) : null}
                {(detailTopologyQuery.data?.edges ?? []).map((edge) => {
                  const outgoing = edge.source.id === selectedAssetId
                  const peer = outgoing ? edge.target : edge.source
                  return (
                    <article className="activity-item" key={edge.id}>
                      <header>
                        <strong>
                          {outgoing ? edge.forward_label : edge.reverse_label}
                        </strong>
                        <span>{edge.relationship_type_code}</span>
                      </header>
                      <p>
                        {peer.name} · {peer.ci_class_name ?? peer.ci_class_code}
                        {' · '}{peer.environment} · {peer.criticality}
                      </p>
                    </article>
                  )
                })}
                {selectedAsset?.ci_class_id ? (
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => {
                      setTopologyRootId(selectedAsset.id)
                      setActiveMode('topology')
                      closeDetail()
                    }}
                  >
                    Открыть полную карту
                  </button>
                ) : null}
              </div>
            ) : null}

            {detailTab === 'governance' ? (
              <div className="activity-list">
                {!selectedAsset?.ci_class_id ? (
                  <p className="empty-state">Актив ещё не классифицирован как CI.</p>
                ) : null}
                {detailOwnershipQuery.isPending ? (
                  <p className="loading-state">Загрузка происхождения полей…</p>
                ) : null}
                {detailOwnershipQuery.isError ? (
                  <p className="form-error">{mutationError(detailOwnershipQuery.error)}</p>
                ) : null}
                {selectedAsset?.ci_class_id
                  && !detailOwnershipQuery.isPending
                  && (detailOwnershipQuery.data?.length ?? 0) === 0 ? (
                    <p className="empty-state">
                      Поля пока не закреплены за автоматизированными источниками.
                    </p>
                  ) : null}
                {(detailOwnershipQuery.data ?? []).map((ownership) => (
                  <article className="activity-item" key={ownership.id}>
                    <header>
                      <strong>{ownership.field_name}</strong>
                      <span>Приоритет {ownership.source_priority}</span>
                    </header>
                    <p>
                      {ownership.source_name} · {ownership.source_code}
                      {' · external ID '}{ownership.external_id}
                      {' · наблюдалось '}{formatDateTime(ownership.observed_at)}
                    </p>
                  </article>
                ))}
              </div>
            ) : null}

            {detailTab === 'impact' ? (
              selectedAsset?.ci_class_id ? (
                <CMDBImpactPanel
                  accessToken={session?.access_token ?? ''}
                  tenantId={selectedAsset.tenant_id}
                  rootCiIds={[selectedAsset.id]}
                  title="Blast radius CI"
                />
              ) : (
                <p className="empty-state">Для анализа влияния актив должен быть зарегистрирован как CI.</p>
              )
            ) : null}

            {detailTab === 'tickets' ? (
              <div className="activity-list">
                {(selectedAsset?.linked_tickets_summary ?? []).length === 0 ? <p className="empty-state">Связанных заявок нет.</p> : null}
                {(selectedAsset?.linked_tickets_summary ?? []).map((item) => (
                  <article className="activity-item" key={item.id}>
                    <header><strong>{item.ticket_number ?? item.id}</strong><span>{item.status}</span></header>
                    <p>{item.title}</p>
                  </article>
                ))}
              </div>
            ) : null}

            {detailTab === 'history' ? (
              <div className="activity-list">
                {selectedAssetHistory.length === 0 ? <p className="empty-state">История актива пока пуста.</p> : null}
                {selectedAssetHistory.map((item) => (
                  <article className="activity-item" key={item.id}>
                    <header><strong>{item.action}</strong><span>{formatDateTime(item.created_at)}</span></header>
                    <p>{item.comment ?? '—'}</p>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {actionModalType ? (
        <div className="modal-backdrop" role="presentation" onClick={closeActionModal}>
          <section
            ref={actionDialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="asset-action-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="asset-action-dialog-title">
                {actionModalType === 'move' ? 'Переместить' : null}
                {actionModalType === 'assign' ? 'Закрепить' : null}
                {actionModalType === 'verify' ? 'Проверить' : null}
                {actionModalType === 'dispose' ? 'Списать' : null}
                {actionModalType === 'restore' ? 'Восстановить' : null}
              </h2>
              <button type="button" className="ghost-button" onClick={closeActionModal}>Закрыть</button>
            </div>

            {actionModalType === 'move' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) moveMutation.mutate(actionAssetId) }}>
                <label><span>building</span><input value={moveForm.building} onChange={(event) => setMoveForm((s) => ({ ...s, building: event.target.value }))} /></label>
                <label><span>floor</span><input value={moveForm.floor} onChange={(event) => setMoveForm((s) => ({ ...s, floor: event.target.value }))} /></label>
                <label><span>room</span><input value={moveForm.room} onChange={(event) => setMoveForm((s) => ({ ...s, room: event.target.value }))} /></label>
                <label><span>location_label</span><input value={moveForm.location_label} onChange={(event) => setMoveForm((s) => ({ ...s, location_label: event.target.value }))} /></label>
                <label><span>comment</span><textarea value={moveForm.comment} onChange={(event) => setMoveForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <button type="submit" disabled={moveMutation.isPending}>Сохранить</button>
              </form>
            ) : null}

            {actionModalType === 'assign' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) assignMutation.mutate(actionAssetId) }}>
                <label><span>responsible_person_name</span><input value={assignForm.responsible_person_name} onChange={(event) => setAssignForm((s) => ({ ...s, responsible_person_name: event.target.value }))} required /></label>
                <label><span>responsible_department</span><input value={assignForm.responsible_department} onChange={(event) => setAssignForm((s) => ({ ...s, responsible_department: event.target.value }))} /></label>
                <label><span>mol_name</span><input value={assignForm.mol_name} onChange={(event) => setAssignForm((s) => ({ ...s, mol_name: event.target.value }))} /></label>
                <label><span>mol_department</span><input value={assignForm.mol_department} onChange={(event) => setAssignForm((s) => ({ ...s, mol_department: event.target.value }))} /></label>
                <label><span>comment</span><textarea value={assignForm.comment} onChange={(event) => setAssignForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <button type="submit" disabled={assignMutation.isPending}>Сохранить</button>
              </form>
            ) : null}

            {actionModalType === 'verify' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) verifyMutation.mutate(actionAssetId) }}>
                <label><span>verification_status</span><select value={verifyForm.verification_status} onChange={(event) => setVerifyForm((s) => ({ ...s, verification_status: event.target.value }))}><option value="verified">verified</option><option value="pending">pending</option><option value="needs_location">needs_location</option><option value="failed">failed</option></select></label>
                <label><span>comment</span><textarea value={verifyForm.comment} onChange={(event) => setVerifyForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <button type="submit" disabled={verifyMutation.isPending}>Сохранить</button>
              </form>
            ) : null}

            {actionModalType === 'dispose' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId && disposeForm.confirm) disposeMutation.mutate(actionAssetId) }}>
                <label><span>writeoff_reason</span><input value={disposeForm.writeoff_reason} onChange={(event) => setDisposeForm((s) => ({ ...s, writeoff_reason: event.target.value }))} required /></label>
                <label><span>comment</span><textarea value={disposeForm.comment} onChange={(event) => setDisposeForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <label><span><input type="checkbox" checked={disposeForm.confirm} onChange={(event) => setDisposeForm((s) => ({ ...s, confirm: event.target.checked }))} /> Подтверждаю списание</span></label>
                <button type="submit" disabled={disposeMutation.isPending || !disposeForm.confirm}>Списать</button>
              </form>
            ) : null}

            {actionModalType === 'restore' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) restoreMutation.mutate(actionAssetId) }}>
                <label><span>comment</span><textarea value={restoreComment} onChange={(event) => setRestoreComment(event.target.value)} /></label>
                <button type="submit" disabled={restoreMutation.isPending}>Восстановить</button>
              </form>
            ) : null}
          </section>
        </div>
      ) : null}
    </AppShell>
    </LocalizedContent>
  )
}
