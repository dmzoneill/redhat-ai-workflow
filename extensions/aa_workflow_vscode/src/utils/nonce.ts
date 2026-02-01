/**
 * Nonce generator for Content Security Policy
 *
 * Generates a random nonce string for use in CSP headers to allow
 * inline scripts in webviews.
 */

/**
 * Generate a random nonce string for CSP
 * @returns A 32-character random alphanumeric string
 */
export function getNonce(): string {
  let text = "";
  const possible =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}
