/**
 * @hermes/plugin-sdk 环境声明（2026-08-23，CoderX）。
 *
 * SDK 由 Hermes 桌面端宿主运行时提供（构建 external，不进仓库）。
 * 本声明只覆盖本插件用到的 API 面。PluginRestOptions 与 Hermes 0.20.5
 * 的权威 SDK 契约保持一致，其余宿主 UI 类型仍按最小兼容面声明。
 */
declare module '@hermes/plugin-sdk' {
  export function atom<T>(initial: T): any
  export const queryClient: any
  export const host: any
  export const cn: any
  export const Codicon: any
  export const Button: any
  export const Input: any
  export const Tip: any
  export const Dialog: any
  export const DialogContent: any
  export const DialogFooter: any
  export const DialogHeader: any
  export const DialogTitle: any
  export const Switch: any
  export function useQuery(...args: any[]): any
  export function useMutation(...args: any[]): any
  export function useValue(...args: any[]): any
  export interface PluginRestOptions {
    method?: string
    body?: unknown
    upload?: { filename: string; contentType?: string; bytes: ArrayBuffer }
    timeoutMs?: number
  }
  export type PluginStorage = any
  export type PluginLocaleBundles = any
  export type HermesPlugin = any
  export type KeybindContribution = any
  export type PaletteContribution = any
  export type RouteContribution = any
  export type SidebarNavContribution = any
  export const KEYBINDS_AREA: any
  export const PALETTE_AREA: any
  export const ROUTES_AREA: any
  export const SIDEBAR_NAV_AREA: any
  export const STATUSBAR_AREAS: any
}

declare module '*.css'
