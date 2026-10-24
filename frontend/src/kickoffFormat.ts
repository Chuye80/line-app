const localeFor = {
  en: "en-US",
  he: "he-IL",
} as const;

/** Present a kickoff in the selected app language, without seconds. The year is included only when it is not the current calendar year. */
export function formatKickoff(
  iso: string,
  language: keyof typeof localeFor
): { date: string; time: string } {
  const value = new Date(iso);
  const locale = localeFor[language];
  const dateOptions: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
  };
  if (value.getFullYear() !== new Date().getFullYear()) {
    dateOptions.year = "numeric";
  }
  return {
    date: new Intl.DateTimeFormat(locale, dateOptions).format(value),
    time: new Intl.DateTimeFormat(locale, {
      hour: "numeric",
      minute: "2-digit",
    }).format(value),
  };
}
