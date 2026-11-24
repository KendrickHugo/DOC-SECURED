package edu.ua.docsecure.portal.security;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Base64;
import javax.crypto.AEADBadTagException;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** AES-256-GCM bridge. Supply the key from a secret manager, never source control. */
public final class CryptoService {
  private static final int IV_BYTES = 12;
  private static final int TAG_BITS = 128;
  private static final SecureRandom RANDOM = new SecureRandom();
  private final SecretKeySpec key;

  public CryptoService(String keyBase64) {
    byte[] raw = Base64.getDecoder().decode(keyBase64);
    if (raw.length != 32) {
      throw new IllegalArgumentException("AES-256 requires a 32-byte key");
    }
    this.key = new SecretKeySpec(raw, "AES");
  }

  /** Encrypt UTF-8 bytes; the returned ciphertext contains the 128-bit tag suffix. */
  public Envelope encrypt(byte[] plaintext, byte[] associatedData) throws GeneralSecurityException {
    byte[] iv = new byte[IV_BYTES];
    RANDOM.nextBytes(iv);
    Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
    cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
    if (associatedData != null && associatedData.length > 0) cipher.updateAAD(associatedData);
    byte[] ciphertextAndTag = cipher.doFinal(plaintext);
    return new Envelope(1, "AES-256-GCM", Base64.getEncoder().encodeToString(iv),
        Base64.getEncoder().encodeToString(ciphertextAndTag));
  }

  public byte[] decrypt(Envelope envelope, byte[] associatedData) throws GeneralSecurityException {
    if (envelope.version() != 1 || !"AES-256-GCM".equals(envelope.algorithm())) {
      throw new IllegalArgumentException("Unsupported encrypted payload");
    }
    byte[] iv = Base64.getDecoder().decode(envelope.iv());
    if (iv.length != IV_BYTES) throw new IllegalArgumentException("AES-GCM IV must be 12 bytes");
    byte[] ciphertextAndTag = Base64.getDecoder().decode(envelope.ciphertext());
    Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
    cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
    if (associatedData != null && associatedData.length > 0) cipher.updateAAD(associatedData);
    try {
      return cipher.doFinal(ciphertextAndTag); // Tag verification happens before plaintext is returned.
    } catch (AEADBadTagException exception) {
      throw new GeneralSecurityException("Encrypted payload authentication failed", exception);
    }
  }

  public byte[] decryptUtf8(Envelope envelope, String associatedData) throws GeneralSecurityException {
    byte[] aad = associatedData == null ? null : associatedData.getBytes(StandardCharsets.UTF_8);
    return decrypt(envelope, aad);
  }

  public record Envelope(int version, String algorithm, String iv, String ciphertext) {}
}
