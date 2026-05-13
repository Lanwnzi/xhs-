/// <reference types="vite/client" />

declare module 'element-plus' {
  import type { Plugin, Component, App } from 'vue'

  const ElementPlus: Plugin
  export default ElementPlus

  // Commonly used named exports
  export const ElMessage: {
    success(message: string): void
    warning(message: string): void
    info(message: string): void
    error(message: string): void
  }
  export const ElMessageBox: any
  export const ElNotification: any
  export const ElLoading: any

  // Re-export common types
  export type FormInstance = any
  export type FormRules = any
  export type UploadInstance = any
}

declare module 'element-plus/dist/index.css' {
  const content: string
  export default content
}

declare module '@element-plus/icons-vue' {
  import type { Component } from 'vue'
  const icons: Record<string, Component>
  export = icons
}
