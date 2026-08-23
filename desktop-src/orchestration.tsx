/**
 * Workbench orchestration — filter/display settings panel.
 * Controls: show archived sections toggle, filter text, section collapse.
 */
import {
  Button,
  cn,
  Codicon,
  Input,
  Switch,
  useValue,
} from '@hermes/plugin-sdk'

import { $collapsedSections, $filterText, $showArchived } from './api'
import { PARTITION_META } from './types'

export function WorkbenchSettings() {
  const showArchived = useValue($showArchived)
  const filterText = useValue($filterText)
  const collapsed = useValue($collapsedSections)

  const toggleSection = (key: string) => {
    const current = $collapsedSections.get()
    $collapsedSections.set({ ...current, [key]: !current[key] })
  }

  return (
    <div className="flex flex-col gap-4 border-t border-(--ui-stroke-tertiary) px-4 py-3">
      {/* Filter */}
      <label className="flex min-w-0 flex-col gap-1">
        <span className="text-[0.6875rem] font-medium text-(--ui-text-secondary)">
          筛选
        </span>
        <Input
          className="h-7 w-60 text-[0.71rem]"
          placeholder="按标题或文件名筛选…"
          value={filterText}
          onChange={(e) => $filterText.set(e.target.value)}
        />
      </label>

      {/* Show archived */}
      <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-[0.75rem] text-(--ui-text-secondary)">
        <Switch
          aria-label="显示已归档"
          checked={showArchived}
          onCheckedChange={(c) => $showArchived.set(c)}
          size="xs"
        />
        显示已归档（已处理 + 回收站）
      </label>

      {/* Section collapse toggles */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[0.6875rem] font-medium text-(--ui-text-secondary)">
          分区折叠
        </span>
        {Object.entries(PARTITION_META).map(([key, meta]) => (
          <label
            key={key}
            className="flex cursor-pointer items-center gap-2 text-[0.6875rem] text-(--ui-text-primary)"
          >
            <Switch
              aria-label={`折叠 ${meta.label}`}
              checked={!!collapsed[key]}
              onCheckedChange={() => toggleSection(key)}
              size="xs"
            />
            <Codicon name={meta.codicon} size="0.7rem" style={{ color: meta.tone }} />
            <span>{meta.label}</span>
          </label>
        ))}
      </div>
    </div>
  )
}