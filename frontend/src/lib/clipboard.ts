// Copying text to the clipboard (the question's copy button, the answer's Copy SQL).

/** Puts the text on the clipboard -> true when it worked. The clipboard API needs https or localhost: on a
 *  plain http address in the office the old way (a hidden text box + the browser's copy command) is used. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // not allowed here: the old way below
  }
  try {
    const box = document.createElement('textarea')
    box.value = text
    box.setAttribute('readonly', '')
    box.style.cssText = 'position:fixed;top:0;left:0;opacity:0'
    document.body.appendChild(box)
    box.select()
    const done = document.execCommand('copy')
    box.remove()
    return done
  } catch {
    return false
  }
}
