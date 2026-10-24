import { useEffect, useState } from "react";
import { signedAvatarUrl } from "./avatarStorage";
import { avatarInitials } from "./profileUtils";

export function GroupPicture({
  name,
  picturePath,
  pictureVersion = 0,
  size = "home",
}: {
  name: string;
  picturePath?: string | null;
  pictureVersion?: number;
  size?: "home" | "editor";
}) {
  const pictureKey = picturePath ? `${picturePath}:${pictureVersion}` : "";
  const [resolved, setResolved] = useState<{ key: string; url: string | null }>({
    key: "",
    url: null,
  });
  const [failedKey, setFailedKey] = useState("");

  useEffect(() => {
    let active = true;
    if (picturePath) {
      signedAvatarUrl(picturePath, pictureVersion).then((value) => {
        if (active) setResolved({ key: pictureKey, url: value });
      });
    }
    return () => {
      active = false;
    };
  }, [pictureKey, picturePath, pictureVersion]);

  const url = resolved.key === pictureKey ? resolved.url : null;
  const failed = Boolean(pictureKey) && failedKey === pictureKey;
  return (
    <span
      className={["group-picture", size === "editor" ? "group-picture-editor" : ""]
        .filter(Boolean)
        .join(" ")}
      aria-label={name}
      title={name}
    >
      {url && !failed ? (
        <img src={url} alt="" onError={() => setFailedKey(pictureKey)} />
      ) : (
        <span aria-hidden="true">{avatarInitials({ name })}</span>
      )}
    </span>
  );
}
