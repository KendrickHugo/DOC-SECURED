/* AES-256-GCM envelope helpers. Keys must arrive over an authenticated session;
   never embed a production key or derive one from a password in client code. */
window.PortalCrypto = (() => {
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();

  function toBase64(bytes) {
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    return btoa(binary);
  }

  function fromBase64(value) {
    return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
  }

  async function importKey(rawKeyBase64) {
    const rawKey = fromBase64(rawKeyBase64);
    if (rawKey.byteLength !== 32) throw new Error("AES-256 requires a 32-byte key.");
    return crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
  }

  async function encryptObject(value, rawKeyBase64, additionalData = "") {
    const key = await importKey(rawKeyBase64);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const options = { name: "AES-GCM", iv, tagLength: 128 };
    if (additionalData) options.additionalData = encoder.encode(additionalData);
    const ciphertext = await crypto.subtle.encrypt(options, key, encoder.encode(JSON.stringify(value)));
    return { version: 1, algorithm: "AES-256-GCM", iv: toBase64(iv), ciphertext: toBase64(new Uint8Array(ciphertext)) };
  }

  async function decryptObject(envelope, rawKeyBase64, additionalData = "") {
    if (!envelope || envelope.algorithm !== "AES-256-GCM" || envelope.version !== 1) throw new Error("Unsupported encrypted payload.");
    const key = await importKey(rawKeyBase64);
    const options = { name: "AES-GCM", iv: fromBase64(envelope.iv), tagLength: 128 };
    if (additionalData) options.additionalData = encoder.encode(additionalData);
    const plaintext = await crypto.subtle.decrypt(options, key, fromBase64(envelope.ciphertext));
    return JSON.parse(decoder.decode(plaintext));
  }

  return { encryptObject, decryptObject };
})();
