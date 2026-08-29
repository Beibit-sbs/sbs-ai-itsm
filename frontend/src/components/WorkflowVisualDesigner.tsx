import { useEffect, useMemo, useState } from 'react'
import type {
  ProductionWorkflow,
  WorkflowCatalog,
  WorkflowDefinitionDocument,
} from '../api/client'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type WorkflowNode = Record<string, unknown> & {
  key: string
  type: string
  name?: string
  config?: Record<string, unknown>
  next?: string | Record<string, string>
  retry?: { max_attempts?: number; backoff_seconds?: number }
  compensation?: Record<string, unknown>
}

type Props = {
  definition: WorkflowDefinitionDocument
  catalog: WorkflowCatalog | undefined
  workflows: ProductionWorkflow[]
  currentWorkflowId: string
  readOnly: boolean
  onChange: (definition: WorkflowDefinitionDocument) => void
}

const nodeTypeLabels: Record<string, string> = {
  CONDITION: 'Условие',
  ACTION: 'Действие',
  WAIT: 'Таймер',
  APPROVAL: 'Согласование',
  SUBFLOW: 'Subflow',
  END: 'Завершение',
}

function cloneDefinition(definition: WorkflowDefinitionDocument) {
  return structuredClone(definition)
}

function defaultNode(
  type: string,
  key: string,
  target: string,
  catalog: WorkflowCatalog | undefined,
  workflows: ProductionWorkflow[],
  currentWorkflowId: string,
): WorkflowNode {
  if (type === 'CONDITION') {
    return {
      key,
      type,
      name: 'Новое условие',
      config: { path: 'context.ticket.priority', operator: 'eq', value: 'HIGH' },
      next: { true: target, false: target },
    }
  }
  if (type === 'WAIT') {
    return {
      key,
      type,
      name: 'Ожидание',
      config: { seconds: 60 },
      next: target,
    }
  }
  if (type === 'APPROVAL') {
    return {
      key,
      type,
      name: 'Согласование',
      config: {
        approver_role: 'it_manager',
        timeout_minutes: 1_440,
        allow_self_approval: false,
      },
      next: { approved: target, rejected: target, timeout: target },
    }
  }
  if (type === 'SUBFLOW') {
    const targetWorkflow =
      workflows.find((workflow) => workflow.id !== currentWorkflowId) ?? null
    return {
      key,
      type,
      name: 'Переиспользуемый subflow',
      config: {
        workflow_code: targetWorkflow?.code ?? 'shared_subflow',
        context: {
          entity_type: '${context.entity_type}',
          entity_id: '${context.entity_id}',
        },
        max_wait_seconds: 86_400,
        failure_policy: 'FAIL',
      },
      next: target,
    }
  }
  if (type === 'END') {
    return { key, type, name: 'Завершение', config: {} }
  }
  return {
    key,
    type: 'ACTION',
    name: 'Новое действие',
    config: {
      action: catalog?.actions[0]?.code ?? 'context.set_variable',
      name: 'result',
      value: 'done',
    },
    retry: { max_attempts: 3, backoff_seconds: 30 },
    next: target,
  }
}

function replaceTarget(
  next: string | Record<string, string> | undefined,
  from: string,
  to: string,
) {
  if (typeof next === 'string') return next === from ? to : next
  if (!next || typeof next !== 'object') return next
  return Object.fromEntries(
    Object.entries(next).map(([branch, target]) => [
      branch,
      target === from ? to : target,
    ]),
  )
}

function JsonConfigEditor({
  value,
  readOnly,
  onChange,
}: {
  value: Record<string, unknown>
  readOnly: boolean
  onChange: (value: Record<string, unknown>) => void
}) {
  const serialized = JSON.stringify(value, null, 2)
  const [text, setText] = useState(serialized)
  const [error, setError] = useState('')

  useEffect(() => setText(serialized), [serialized])

  return (
    <label className="workflow-node-json">
      <span>Конфигурация action (JSON)</span>
      <textarea
        value={text}
        readOnly={readOnly}
        spellCheck={false}
        onChange={(event) => {
          const nextText = event.target.value
          setText(nextText)
          try {
            const parsed = JSON.parse(nextText) as unknown
            if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
              throw new Error('Ожидается JSON-объект')
            }
            setError('')
            onChange(parsed as Record<string, unknown>)
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : 'Некорректный JSON')
          }
        }}
      />
      {error ? <small className="workflow-field-error">{error}</small> : null}
    </label>
  )
}

export default function WorkflowVisualDesigner({
  definition,
  catalog,
  workflows,
  currentWorkflowId,
  readOnly,
  onChange,
}: Props) {
  const { translate } = useTenantExperience()
  const nodes = definition.nodes as WorkflowNode[]
  const [newType, setNewType] = useState('ACTION')
  const nodeKeys = useMemo(() => nodes.map((node) => node.key), [nodes])

  const commitNodes = (
    nextNodes: WorkflowNode[],
    entrypoint = definition.entrypoint,
  ) => {
    onChange({
      ...definition,
      entrypoint,
      nodes: nextNodes,
    })
  }

  const patchNode = (index: number, patch: Partial<WorkflowNode>) => {
    const nextDefinition = cloneDefinition(definition)
    const nextNodes = nextDefinition.nodes as WorkflowNode[]
    const previousKey = nextNodes[index].key
    const nextKey = String(patch.key ?? previousKey)
    nextNodes[index] = { ...nextNodes[index], ...patch }
    if (nextKey !== previousKey) {
      nextDefinition.entrypoint =
        nextDefinition.entrypoint === previousKey
          ? nextKey
          : nextDefinition.entrypoint
      nextDefinition.nodes = nextNodes.map((node) => ({
        ...node,
        next: replaceTarget(node.next, previousKey, nextKey),
      }))
    }
    onChange(nextDefinition)
  }

  const changeNodeType = (index: number, type: string) => {
    const existing = nodes[index]
    const fallback =
      typeof existing.next === 'string'
        ? existing.next
        : Object.values(existing.next ?? {})[0] ?? nodeKeys.find((key) => key !== existing.key) ?? existing.key
    const nextDefinition = cloneDefinition(definition)
    const nextNodes = nextDefinition.nodes as WorkflowNode[]
    nextNodes[index] = defaultNode(
      type,
      existing.key,
      fallback,
      catalog,
      workflows,
      currentWorkflowId,
    )
    onChange(nextDefinition)
  }

  const addNode = (type = newType) => {
    const nextNodes = structuredClone(nodes)
    const used = new Set(nodeKeys)
    let index = nextNodes.length + 1
    let key = `step_${index}`
    while (used.has(key)) {
      index += 1
      key = `step_${index}`
    }
    const end = nextNodes.find((node) => node.type === 'END')
    const target = end?.key ?? definition.entrypoint
    const node = defaultNode(
      type,
      key,
      target,
      catalog,
      workflows,
      currentWorkflowId,
    )
    if (type === 'END') {
      nextNodes.push(node)
      commitNodes(nextNodes)
      return
    }
    const predecessorIndex = nextNodes.findIndex(
      (candidate) => candidate.next === target,
    )
    let entrypoint = definition.entrypoint
    if (predecessorIndex >= 0) {
      nextNodes[predecessorIndex] = {
        ...nextNodes[predecessorIndex],
        next: key,
      }
    } else if (definition.entrypoint === target) {
      entrypoint = key
    }
    const targetIndex = nextNodes.findIndex((candidate) => candidate.key === target)
    if (targetIndex >= 0) nextNodes.splice(targetIndex, 0, node)
    else nextNodes.push(node)
    commitNodes(nextNodes, entrypoint)
  }

  const removeNode = (index: number) => {
    const removed = nodes[index]
    if (removed.type === 'END' && nodes.filter((node) => node.type === 'END').length === 1) {
      return
    }
    const fallback =
      typeof removed.next === 'string'
        ? removed.next
        : Object.values(removed.next ?? {})[0] ??
          nodes.find((node) => node.key !== removed.key)?.key ??
          ''
    const nextNodes = nodes
      .filter((_, nodeIndex) => nodeIndex !== index)
      .map((node) => ({
        ...node,
        next: replaceTarget(node.next, removed.key, fallback),
      }))
    commitNodes(
      nextNodes,
      definition.entrypoint === removed.key ? fallback : definition.entrypoint,
    )
  }

  const moveNode = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= nodes.length) return
    const nextNodes = structuredClone(nodes)
    const [node] = nextNodes.splice(index, 1)
    nextNodes.splice(target, 0, node)
    commitNodes(nextNodes)
  }

  const patchConfig = (
    index: number,
    values: Record<string, unknown>,
  ) => {
    patchNode(index, {
      config: { ...(nodes[index].config ?? {}), ...values },
    })
  }

  const patchBranch = (index: number, branch: string, value: string) => {
    const next =
      nodes[index].next && typeof nodes[index].next === 'object'
        ? { ...nodes[index].next }
        : {}
    next[branch] = value
    patchNode(index, { next })
  }

  return (
    <LocalizedContent>
      <section className="workflow-visual-designer">
      <header className="workflow-visual-toolbar">
        <div>
          <p className="eyebrow">ACCESSIBLE NODE DESIGNER</p>
          <h3>Визуальная схема</h3>
        </div>
        {!readOnly ? (
          <div>
            <select value={newType} onChange={(event) => setNewType(event.target.value)}>
              {(catalog?.node_types ?? Object.keys(nodeTypeLabels)).map((type) => (
                <option key={type} value={type}>
                  {nodeTypeLabels[type] ? translate(nodeTypeLabels[type]) : type}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => addNode()}>
              Добавить узел
            </button>
          </div>
        ) : null}
      </header>

      {!readOnly ? (
        <div className="workflow-pattern-library">
          <span>Быстрые блоки:</span>
          <button type="button" onClick={() => addNode('CONDITION')}>Условие</button>
          <button type="button" onClick={() => addNode('APPROVAL')}>Approval gate</button>
          <button type="button" onClick={() => addNode('WAIT')}>Таймер</button>
          <button type="button" onClick={() => addNode('SUBFLOW')}>Reusable subflow</button>
        </div>
      ) : null}

      <div className="workflow-entrypoint">
        <label>
          <span>Точка входа</span>
          <select
            value={definition.entrypoint}
            disabled={readOnly}
            onChange={(event) =>
              onChange({ ...definition, entrypoint: event.target.value })
            }
          >
            {nodeKeys.map((key) => <option key={key} value={key}>{key}</option>)}
          </select>
        </label>
        <label>
          <span>При ошибке</span>
          <select
            value={definition.on_failure ?? 'FAIL'}
            disabled={readOnly}
            onChange={(event) =>
              onChange({ ...definition, on_failure: event.target.value })
            }
          >
            <option value="FAIL">Остановить</option>
            <option value="COMPENSATE">Компенсировать</option>
          </select>
        </label>
      </div>

      <div className="workflow-node-list">
        {nodes.map((node, index) => {
          const config = node.config ?? {}
          return (
            <article
              key={`${node.key}-${index}`}
              className={`workflow-node node-${node.type.toLowerCase()}`}
            >
              <div className="workflow-node-order">
                <span>{index + 1}</span>
                {!readOnly ? (
                  <>
                    <button
                      type="button"
                      aria-label={`${translate('Переместить')} ${node.key} ${translate('выше')}`}
                      disabled={index === 0}
                      onClick={() => moveNode(index, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`${translate('Переместить')} ${node.key} ${translate('ниже')}`}
                      disabled={index === nodes.length - 1}
                      onClick={() => moveNode(index, 1)}
                    >
                      ↓
                    </button>
                  </>
                ) : null}
              </div>
              <div className="workflow-node-body">
                <div className="workflow-node-heading">
                  <label>
                    <span>Тип</span>
                    <select
                      value={node.type}
                      disabled={readOnly}
                      onChange={(event) => changeNodeType(index, event.target.value)}
                    >
                      {(catalog?.node_types ?? Object.keys(nodeTypeLabels)).map((type) => (
                        <option key={type} value={type}>
                          {nodeTypeLabels[type] ? translate(nodeTypeLabels[type]) : type}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Ключ</span>
                    <input
                      value={node.key}
                      readOnly={readOnly}
                      onChange={(event) => patchNode(index, { key: event.target.value })}
                    />
                  </label>
                  <label className="workflow-node-name">
                    <span>Название</span>
                    <input
                      value={String(node.name ?? '')}
                      readOnly={readOnly}
                      onChange={(event) => patchNode(index, { name: event.target.value })}
                    />
                  </label>
                  {!readOnly ? (
                    <button
                      type="button"
                      className="workflow-node-remove"
                      disabled={
                        node.type === 'END' &&
                        nodes.filter((candidate) => candidate.type === 'END').length === 1
                      }
                      onClick={() => removeNode(index)}
                    >
                      Удалить
                    </button>
                  ) : null}
                </div>

                {node.type === 'CONDITION' ? (
                  <div className="workflow-node-config-grid">
                    <label>
                      <span>Путь</span>
                      <input
                        value={String(config.path ?? '')}
                        readOnly={readOnly}
                        onChange={(event) => patchConfig(index, { path: event.target.value })}
                      />
                    </label>
                    <label>
                      <span>Оператор</span>
                      <select
                        value={String(config.operator ?? 'eq')}
                        disabled={readOnly}
                        onChange={(event) => patchConfig(index, { operator: event.target.value })}
                      >
                        {['eq', 'ne', 'contains', 'in', 'exists', 'not_exists', 'gt', 'gte', 'lt', 'lte'].map((operator) => (
                          <option key={operator} value={operator}>{operator}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Значение</span>
                      <input
                        value={String(config.value ?? '')}
                        readOnly={readOnly}
                        onChange={(event) => patchConfig(index, { value: event.target.value })}
                      />
                    </label>
                  </div>
                ) : null}

                {node.type === 'ACTION' ? (
                  <>
                    <div className="workflow-node-config-grid">
                      <label>
                        <span>Action</span>
                        <select
                          value={String(config.action ?? '')}
                          disabled={readOnly}
                          onChange={(event) =>
                            patchConfig(index, { action: event.target.value })
                          }
                        >
                          {(catalog?.actions ?? []).map((action) => (
                            <option key={action.code} value={action.code}>
                              {action.code}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Попытки</span>
                        <input
                          type="number"
                          min={1}
                          max={10}
                          value={node.retry?.max_attempts ?? 1}
                          readOnly={readOnly}
                          onChange={(event) =>
                            patchNode(index, {
                              retry: {
                                ...(node.retry ?? {}),
                                max_attempts: Number(event.target.value),
                              },
                            })
                          }
                        />
                      </label>
                      <label>
                        <span>Backoff, сек.</span>
                        <input
                          type="number"
                          min={1}
                          max={3_600}
                          value={node.retry?.backoff_seconds ?? 30}
                          readOnly={readOnly}
                          onChange={(event) =>
                            patchNode(index, {
                              retry: {
                                ...(node.retry ?? {}),
                                backoff_seconds: Number(event.target.value),
                              },
                            })
                          }
                        />
                      </label>
                    </div>
                    <JsonConfigEditor
                      value={config}
                      readOnly={readOnly}
                      onChange={(value) => patchNode(index, { config: value })}
                    />
                  </>
                ) : null}

                {node.type === 'WAIT' ? (
                  <div className="workflow-node-config-grid">
                    <label>
                      <span>Ожидание, секунд</span>
                      <input
                        type="number"
                        min={1}
                        max={2_592_000}
                        value={Number(config.seconds ?? 60)}
                        readOnly={readOnly}
                        onChange={(event) =>
                          patchConfig(index, { seconds: Number(event.target.value) })
                        }
                      />
                    </label>
                  </div>
                ) : null}

                {node.type === 'APPROVAL' ? (
                  <div className="workflow-node-config-grid">
                    <label>
                      <span>Роль согласующего</span>
                      <input
                        value={String(config.approver_role ?? 'it_manager')}
                        readOnly={readOnly}
                        onChange={(event) =>
                          patchConfig(index, { approver_role: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      <span>Timeout, минут</span>
                      <input
                        type="number"
                        min={1}
                        max={43_200}
                        value={Number(config.timeout_minutes ?? 1_440)}
                        readOnly={readOnly}
                        onChange={(event) =>
                          patchConfig(index, {
                            timeout_minutes: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                    <label className="workflow-checkbox">
                      <input
                        type="checkbox"
                        checked={Boolean(config.allow_self_approval)}
                        disabled={readOnly}
                        onChange={(event) =>
                          patchConfig(index, {
                            allow_self_approval: event.target.checked,
                          })
                        }
                      />
                      <span>Разрешить self-approval</span>
                    </label>
                  </div>
                ) : null}

                {node.type === 'SUBFLOW' ? (
                  <div className="workflow-node-config-grid">
                    <label>
                      <span>Workflow</span>
                      <select
                        value={String(config.workflow_code ?? '')}
                        disabled={readOnly}
                        onChange={(event) =>
                          patchConfig(index, { workflow_code: event.target.value })
                        }
                      >
                        <option value="">Выберите workflow</option>
                        {workflows
                          .filter((workflow) => workflow.id !== currentWorkflowId)
                          .map((workflow) => (
                            <option key={workflow.id} value={workflow.code}>
                              {workflow.name} · {workflow.status}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      <span>Max wait, секунд</span>
                      <input
                        type="number"
                        min={60}
                        max={2_592_000}
                        value={Number(config.max_wait_seconds ?? 86_400)}
                        readOnly={readOnly}
                        onChange={(event) =>
                          patchConfig(index, {
                            max_wait_seconds: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                    <label>
                      <span>При ошибке subflow</span>
                      <select
                        value={String(config.failure_policy ?? 'FAIL')}
                        disabled={readOnly}
                        onChange={(event) =>
                          patchConfig(index, { failure_policy: event.target.value })
                        }
                      >
                        <option value="FAIL">Остановить parent</option>
                        <option value="CONTINUE">Продолжить parent</option>
                      </select>
                    </label>
                    <JsonConfigEditor
                      value={
                        config.context && typeof config.context === 'object'
                          ? (config.context as Record<string, unknown>)
                          : {}
                      }
                      readOnly={readOnly}
                      onChange={(value) => patchConfig(index, { context: value })}
                    />
                  </div>
                ) : null}

                {node.type !== 'END' ? (
                  <div className="workflow-node-branches">
                    {node.type === 'CONDITION'
                      ? ['true', 'false'].map((branch) => (
                          <label key={branch}>
                            <span>{branch}</span>
                            <select
                              value={String(
                                typeof node.next === 'object'
                                  ? node.next[branch] ?? ''
                                  : '',
                              )}
                              disabled={readOnly}
                              onChange={(event) =>
                                patchBranch(index, branch, event.target.value)
                              }
                            >
                              {nodeKeys.filter((key) => key !== node.key).map((key) => (
                                <option key={key} value={key}>{key}</option>
                              ))}
                            </select>
                          </label>
                        ))
                      : node.type === 'APPROVAL'
                        ? ['approved', 'rejected', 'timeout'].map((branch) => (
                            <label key={branch}>
                              <span>{branch}</span>
                              <select
                                value={String(
                                  typeof node.next === 'object'
                                    ? node.next[branch] ?? ''
                                    : '',
                                )}
                                disabled={readOnly}
                                onChange={(event) =>
                                  patchBranch(index, branch, event.target.value)
                                }
                              >
                                {nodeKeys.filter((key) => key !== node.key).map((key) => (
                                  <option key={key} value={key}>{key}</option>
                                ))}
                              </select>
                            </label>
                          ))
                        : (
                            <label>
                              <span>Следующий узел</span>
                              <select
                                value={typeof node.next === 'string' ? node.next : ''}
                                disabled={readOnly}
                                onChange={(event) =>
                                  patchNode(index, { next: event.target.value })
                                }
                              >
                                {nodeKeys.filter((key) => key !== node.key).map((key) => (
                                  <option key={key} value={key}>{key}</option>
                                ))}
                              </select>
                            </label>
                          )}
                  </div>
                ) : (
                  <p className="workflow-terminal-note">Терминальный узел — переходы отсутствуют.</p>
                )}
              </div>
            </article>
          )
        })}
      </div>

      <aside className="workflow-graph-summary">
        <strong>Связи графа</strong>
        <div>
          {nodes.flatMap((node) => {
            const targets =
              typeof node.next === 'string'
                ? [['next', node.next]]
                : Object.entries(node.next ?? {})
            return targets.map(([branch, target]) => (
              <span key={`${node.key}-${branch}-${target}`}>
                {node.key} <b>→</b> {target}
                {branch !== 'next' ? <small>{branch}</small> : null}
              </span>
            ))
          })}
        </div>
      </aside>
      </section>
    </LocalizedContent>
  )
}
