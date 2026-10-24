import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { signedAvatarUrl } from "./avatarStorage";
import { avatarInitials, type ProfileIdentity } from "./profileUtils";
import championFrame from "./assets/champion-frame.png";
import mvpCrown from "./assets/mvp-crown.png";
import {
  playerHasReigningTitle,
  type ReigningTitles,
} from "./reigningTitles";

const emptyTitles: ReigningTitles = {
  championIds: new Set(),
  mvpIds: new Set(),
};

const ReigningTitlesContext = createContext<ReigningTitles>(emptyTitles);

export function ReigningTitlesProvider({
  titles,
  children,
}: {
  titles: ReigningTitles;
  children: ReactNode;
}) {
  return (
    <ReigningTitlesContext.Provider value={titles}>
      {children}
    </ReigningTitlesContext.Provider>
  );
}

type AvatarIdentity = ProfileIdentity & {
  id?: string | null;
  user_id?: string | null;
  avatar_path?: string | null;
  avatar_version?: number;
};

export function PlayerAvatar({
  player,
  size = "medium",
}: {
  player: AvatarIdentity;
  size?: "small" | "medium" | "large";
}) {
  const titles = useContext(ReigningTitlesContext);
  const champion = playerHasReigningTitle(titles, player, "champion");
  const mvp = playerHasReigningTitle(titles, player, "mvp");
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
      className={[
        "player-avatar",
        `player-avatar-${size}`,
        champion ? "player-avatar-champion" : "",
        mvp ? "player-avatar-mvp" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={label}
      title={label}
    >
      <span className="player-avatar-photo">
        {url && !failed ? (
          <img src={url} alt="" onError={() => setFailedKey(avatarKey)} />
        ) : (
          <span aria-hidden="true">{avatarInitials(player)}</span>
        )}
      </span>
      {champion && (
        <img className="player-avatar-frame" src={championFrame} alt="" />
      )}
      {mvp && <img className="player-avatar-crown" src={mvpCrown} alt="" />}
    </span>
  );
}
