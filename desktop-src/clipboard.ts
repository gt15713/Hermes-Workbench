type ClipboardWriters = {
  nativeWrite?: (text: string) => Promise<void>
  webWrite?: (text: string) => Promise<void>
}

type HermesDesktopWindow = Window & {
  hermesDesktop?: { writeClipboard?: (text: string) => Promise<void> }
}

function runtimeWriters(): ClipboardWriters {
  const nativeWrite = (window as HermesDesktopWindow).hermesDesktop?.writeClipboard
  const webWrite = navigator.clipboard?.writeText?.bind(navigator.clipboard)
  return { nativeWrite, webWrite }
}

export async function writeWorkbenchClipboard(text: string, writers = runtimeWriters()): Promise<void> {
  if (!text) throw new Error('Clipboard text is empty')
  if (writers.nativeWrite) {
    await writers.nativeWrite(text)
    return
  }
  if (writers.webWrite) {
    await writers.webWrite(text)
    return
  }
  throw new Error('Clipboard API is unavailable')
}
