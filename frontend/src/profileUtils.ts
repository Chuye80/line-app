export type ProfileIdentity = {
  name: string;
  full_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  nickname?: string | null;
};

export function avatarInitials(identity: ProfileIdentity): string {
  const first = identity.first_name?.trim();
  const last = identity.last_name?.trim();
  if (first && last) {
    return `${first[0]}${last[0]}`.toLocaleUpperCase();
  }
  const words = (identity.name || identity.full_name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (words.length > 1 ? `${words[0]![0]}${words[1]![0]}` : words[0]?.[0] ?? "?")
    .toLocaleUpperCase();
}

export function matchesMemberSearch(
  identity: ProfileIdentity,
  query: string
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    identity.name,
    identity.full_name,
    identity.first_name,
    identity.last_name,
    identity.nickname,
  ].some((value) => value?.toLocaleLowerCase().includes(needle));
}
