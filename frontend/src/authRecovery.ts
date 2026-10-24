export const MIN_PASSWORD_LENGTH = 6;

export type AuthCallback = {
  recovery: boolean;
  errorCode: string | null;
  errorDescription: string | null;
};

export function parseAuthCallbackHash(hash: string): AuthCallback {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  return {
    recovery: params.get("type") === "recovery",
    errorCode: params.get("error_code"),
    errorDescription: params.get("error_description"),
  };
}

export function recoveryFailureKey(
  callback: AuthCallback
): "recoveryLinkExpired" | "recoveryLinkInvalid" | null {
  if (!callback.errorCode && !callback.errorDescription) return null;
  const expired =
    callback.errorCode === "otp_expired" ||
    /expired/i.test(callback.errorDescription ?? "");
  return expired ? "recoveryLinkExpired" : "recoveryLinkInvalid";
}

export function passwordUpdateError(
  password: string,
  confirmation: string
): "passwordsDoNotMatch" | "passwordTooShort" | null {
  if (password !== confirmation) return "passwordsDoNotMatch";
  if (password.length < MIN_PASSWORD_LENGTH) return "passwordTooShort";
  return null;
}
