import assert from "node:assert/strict";
import test from "node:test";
import {
  parseAuthCallbackHash,
  passwordUpdateError,
  recoveryFailureKey,
} from "../src/authRecovery.ts";
import { translations } from "../src/i18n.ts";

const recoveryCopy = [
  "forgotPassword",
  "forgotPasswordSubtitle",
  "sendRecoveryEmail",
  "recoveryEmailSent",
  "recoveryRateLimited",
  "chooseNewPassword",
  "newPassword",
  "confirmPassword",
  "updatePassword",
  "passwordsDoNotMatch",
  "passwordTooShort",
  "passwordUpdateFailed",
  "recoveryLinkExpired",
  "recoveryLinkInvalid",
];

test("a recovery hash is recognized and is not an error", () => {
  const callback = parseAuthCallbackHash(
    "#access_token=token&refresh_token=refresh&type=recovery"
  );
  assert.equal(callback.recovery, true);
  assert.equal(callback.errorCode, null);
  assert.equal(recoveryFailureKey(callback), null);
});

test("an expired recovery link uses the expired message", () => {
  const callback = parseAuthCallbackHash(
    "#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired"
  );
  assert.equal(callback.recovery, false);
  assert.equal(callback.errorCode, "otp_expired");
  assert.equal(callback.errorDescription, "Email link is invalid or has expired");
  assert.equal(recoveryFailureKey(callback), "recoveryLinkExpired");
});

test("any other auth callback error uses the invalid-link message", () => {
  const callback = parseAuthCallbackHash(
    "#error=access_denied&error_code=otp_disabled&error_description=Signups+not+allowed"
  );
  assert.equal(recoveryFailureKey(callback), "recoveryLinkInvalid");
});

test("recovery copy exists in English and Hebrew", () => {
  for (const key of recoveryCopy) {
    assert.equal(typeof translations.en[key], "string", key);
    assert.equal(typeof translations.he[key], "string", key);
    assert.notEqual(translations.en[key], translations.he[key], key);
  }
});

test("a new password must match and meet the existing minimum length", () => {
  assert.equal(passwordUpdateError("secret", "other"), "passwordsDoNotMatch");
  assert.equal(passwordUpdateError("short", "short"), "passwordTooShort");
  assert.equal(passwordUpdateError("secret1", "secret1"), null);
});
