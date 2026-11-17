// The app's name in one place: the top bar, the sign-in page, the footer and the browser tab.
// The company's own name, with "Intelligence Platform" under it.
export const APP_NAME = 'SS Manufacturing'
export const APP_SUBTITLE = 'Intelligence Platform'
// the footer inside the app, and the one under the sign-in card (no "demo": the app is shown to clients)
export const FOOTER_TEXT = `${APP_NAME} · ${APP_SUBTITLE}`
export const LOGIN_FOOTER_TEXT = 'SS Manufacturing · Secure, read-only access to company data'

/** The browser tab title: "<page> · SS Manufacturing". */
export function tabTitle(page: string): string {
  return page ? `${page} · ${APP_NAME}` : APP_NAME
}
