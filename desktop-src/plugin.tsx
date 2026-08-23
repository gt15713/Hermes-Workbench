/**
 * Workbench — the 7-partition task/file board plugin.
 * Ships OFF by default; user enables in Settings ▸ Plugins.
 *
 * Shares the existing /api/plugins/workbench-view backend (no new backend).
 * The desktop-plugins/workbench-view disk entry is deprecated — this bundled
 * version replaces it.
 */

import './workbench.css'

import {
  cn,
  Codicon,
  type HermesPlugin,
  host,
  type KeybindContribution,
  KEYBINDS_AREA,
  PALETTE_AREA,
  type PaletteContribution,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  type SidebarNavContribution,
  STATUSBAR_AREAS,
  Tip,
  useQuery,
  useValue
} from '@hermes/plugin-sdk'

import { bindApi, BOARD_KEY, fetchBoard, $showArchived, $filterText } from './api'
import { WorkbenchBoardPage } from './board'
import { WB_LOCALES } from './i18n'
import { partitionMeta } from './types'

/** Live pending/total count in the status bar. */
function WbStatusCount() {
  const { data: board } = useQuery({
    queryFn: () => fetchBoard(),
    queryKey: BOARD_KEY,
    refetchInterval: 30_000
  })

  if (!board || board.totals.pending === 0) {
    return null
  }

  return (
    <Tip label={`${board.totals.pending} pending / ${board.totals.total} total`}>
      <button
        className={cn(
          'inline-flex h-full items-center gap-1 rounded-none px-1.5 text-[0.6875rem] tabular-nums transition-colors',
          'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
        )}
        onClick={() => host.navigate('/workbench')}
        type="button"
      >
        <Codicon name="checklist" size="0.7rem" />
        <span>{board.totals.pending}</span>
      </button>
    </Tip>
  )
}

const plugin: HermesPlugin = {
  id: 'workbench-view',
  name: 'Workbench',
  description: '7-partition task/file board — inbox, tasks, psychology, dreams, done, trash.',
  defaultEnabled: false,
  register(ctx) {
    ctx.i18n.register(WB_LOCALES)
    ctx.onDispose(bindApi(ctx.rest, ctx.storage, ctx.socket))

    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/workbench' } satisfies RouteContribution,
        render: () => <WorkbenchBoardPage />
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        order: 45,
        data: { codicon: 'checklist', label: 'Workbench', path: '/workbench' } satisfies SidebarNavContribution
      },
      {
        id: 'count',
        area: STATUSBAR_AREAS.right,
        order: 80,
        render: () => <WbStatusCount />
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'workbench.open',
          label: 'Workbench: Open board',
          keywords: ['workbench', 'board', 'tasks', 'inbox'],
          run: () => host.navigate('/workbench')
        } satisfies PaletteContribution
      },
      {
        id: 'toggle-archived',
        area: PALETTE_AREA,
        data: {
          id: 'workbench.toggleArchived',
          label: 'Workbench: Toggle archived sections',
          keywords: ['workbench', 'archived', 'done', 'trash'],
          run: () => $showArchived.set(!$showArchived.get())
        } satisfies PaletteContribution
      },
      {
        id: 'filter',
        area: PALETTE_AREA,
        data: {
          id: 'workbench.filter',
          label: 'Workbench: Filter cards...',
          keywords: ['workbench', 'filter', 'search'],
          run: () => {
            const input = prompt('Filter workbench cards:')
            if (input !== null) $filterText.set(input)
          }
        } satisfies PaletteContribution
      },
      {
        id: 'new-task',
        area: KEYBINDS_AREA,
        data: {
          id: 'workbench.openBoard',
          category: 'view',
          // Task 5.2 批次 1: aligned to official kanban (Ctrl+Alt+N on Win / Cmd+Alt+N on Mac).
          // Note: previous binding was mod+alt+w; changed per kanban convention.
          defaults: ['mod+alt+n'],
          label: 'Workbench: Open board',
          run: () => host.navigate('/workbench')
        } satisfies KeybindContribution
      }
    ])
  }
}

export default plugin