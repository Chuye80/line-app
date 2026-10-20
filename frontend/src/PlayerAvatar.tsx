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
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setFailed(false);
    setUrl(null);
    if (player.avatar_path) {
      signedAvatarUrl(player.avatar_path, player.avatar_version).then((value) => {
        if (active) setUrl(value);
      });
    }
    return () => {
      active = false;
    };
  }, [player.avatar_path, player.avatar_version]);

  const label = player.full_name || player.name;
  return (
    <span
      className={`player-avatar player-avatar-${size}`}
      aria-label={label}
      title={label}
    >
      {url && !failed ? (
        <img src={url} alt="" onError={() => setFailed(true)} />
      ) : (
        <span aria-hidden="true">{avatarInitials(player)}</span>
      )}
    </span>
  );
}

export async function prepareAvatar(file: File): Promise<Blob> {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    throw new Error("Choose a JPEG, PNG, or WebP image.");
  }
  if (file.size > 5 * 1024 * 1024) {
    throw new Error("Image must be smaller than 5 MB.");
  }
  const bitmap = await createImageBitmap(file);
  const side = Math.min(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Unable to process image.");
  context.drawImage(
    bitmap,
    (bitmap.width - side) / 2,
    (bitmap.height - side) / 2,
    side,
    side,
    0,
    0,
    512,
    512
  );
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/webp", 0.82)
  );
  if (!blob) throw new Error("Unable to compress image.");
  return blob;
}

export async function uploadAvatar(prefix: string, file: File): Promise<string> {
  const blob = await prepareAvatar(file);
  const path = `${prefix}${crypto.randomUUID()}.webp`;
  const { error } = await supabase.storage.from(BUCKET).upload(path, blob, {
    cacheControl: "3600",
    contentType: "image/webp",
    upsert: false,
  });
  if (error) throw error;
  return path;
}

export async function removeAvatar(path: string | null | undefined) {
  if (!path) return;
  await supabase.storage.from(BUCKET).remove([path]);
}
