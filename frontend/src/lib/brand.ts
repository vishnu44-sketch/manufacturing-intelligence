// The app's name in one place: the top bar, the sign-in page, the footer and the browser tab.
// SSAGE (said "sage") = SS Advanced Guidance Engine: SS Manufacturing's data assistant.
export const APP_NAME = 'SSAGE'
export const APP_SUBTITLE = 'Manufacturing Intelligence Platform'
export const FOOTER_TEXT = `${APP_NAME} · demo project with synthetic data`

/** The browser tab title: "<page> · SSAGE". */
export function tabTitle(page: string): string {
  return page ? `${page} · ${APP_NAME}` : APP_NAME
}
