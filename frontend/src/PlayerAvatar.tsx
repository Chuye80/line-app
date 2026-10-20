import { useEffect, useState } from "react";
import { supabase } from "./supabase";
import { avatarInitials, type ProfileIdentity } from "./profileUtils";

const BUCKET = "player-avatars";
const signedUrlCache = new Map<string, Promise<string | null>>();

type AvatarIdentity = ProfileIdentity & {
  avatar_path?: string | null;
  avatar_version?: number;
};

function signedAvatarUrl(path: string, version = 0): Promise<string | null> {
  const key = `${path}:${version}`;
  let pending = signedUrlCache.get(key);
  if (!pending) {
    pending = supabase.storage
      .from(BUCKET)
      .createSignedUrl(path, 3600)
      .then(({ data, error }) => (error ? null : data.signedUrl));
    signedUrlCache.set(key, pending);
  }
  return pending;
}

export function PlayerAvatar({
  player,
  size = "medium",
}: {
  player: AvatarIdentity;
  size?: "small" | "medium" | "large";
}) {
  const avatarKey = player.avatar_path
    ? `${player.avatar_path}:${player.avatar_version ?? 0}`
    : "";
  const [resolved, setResolved] = useState<{
    key: string;
    url: string | null;
  }>({ key: "", url: null });
  const [failedKey, setFailedKey] = useState("");

  useEffect(() => {
    let active = true;
    if (player.avatar_path) {
      signedAvatarUrl(player.avatar_path, player.avatar_version).then((value) => {
        if (active) setResolved({ key: avatarKey, url: value });
      });
    }
    return () => {
      active = false;
    };
  }, [avatarKey, player.avatar_path, player.avatar_version]);

  const label = player.full_name || player.name;
  const url = resolved.key === avatarKey ? resolved.url : null;
  const failed = failedKey === avatarKey;
  return (
    <span
      className={`player-avatar player-avatar-${size}`}
      aria-label={label}
      title={label}
    >
      {url && !failed ? (
        <img src={url} alt="" onError={() => setFailedKey(avatarKey)} />
      ) : (
        <span aria-hidden="true">{avatarInitials(player)}</span>
      )}
    </span>
  );
}
