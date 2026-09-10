/**
 * The shapes the API returns.
 *
 * Kept in one place because the game day lifecycle is read by several screens
 * at once - the live experience, the completion screen and the history list all
 * render the same standings and statistics rows.
 */

export type Member = {
  id: string;
  user_id: string | null;
  name: string;
  rating: number;
  is_subscriber: boolean;
  is_admin: boolean;
  is_virtual: boolean;
};

/** Where a game day is in its lifecycle. Stored, never inferred from a clock. */
export type GameStatus = "scheduled" | "live" | "finished";

export type Game = {
  id: string;
  status: GameStatus;
  game_datetime: string;
  regular_registration_opens: string;
  started_at: string | null;
  finished_at: string | null;
  participants: Member[];
  waiting_list: Member[];
};

export type Team = {
  name: string;
  players: Member[];
  total_rating: number;
  average_rating: number;
};

export type Group = {
  id: string;
  name: string;
  members: Member[];
  game: Game | null;
  teams: Team[];
};

export type GroupSummary = {
  id: string;
  name: string;
};

export type MyGroup = {
  id: string;
  name: string;
  membership_id: string;
  is_admin: boolean;
  is_subscriber: boolean;
  rating: number;
};

export type MembershipStatus = {
  state: "none" | "pending" | "approved" | "declined" | "member";
  membership_id: string | null;
  is_admin: boolean;
};

export type JoinRequest = {
  id: string;
  user_id: string;
  user_name: string;
  status: string;
};

export type MatchStatus = "scheduled" | "live" | "completed";

export type Goal = {
  id: string;
  team_name: string;
  scorer_membership_id: string | null;
  scorer_name: string;
  assist_membership_id: string | null;
  assist_name: string | null;
};

export type Match = {
  id: string;
  match_order: number;
  home_team: string;
  away_team: string;
  status: MatchStatus;
  home_score: number;
  away_score: number;
  started_at: string | null;
  completed_at: string | null;
  goals: Goal[];
};

export type StandingsRow = {
  position: number;
  team: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
};

export type PlayerStatsRow = {
  membership_id: string;
  name: string;
  is_virtual: boolean;
  matches: number;
  wins: number;
  draws: number;
  losses: number;
  goals: number;
  assists: number;
  points: number;
  admin_rating: number;
  /** Only in the accumulated statistics. */
  game_days?: number;
  survey_rating?: number | null;
  survey_responses?: number;
};

export type GameDay = {
  id: string;
  status: GameStatus;
  game_datetime: string;
  started_at: string | null;
  finished_at: string | null;
  teams: Team[];
  matches: Match[];
  current_match_id: string | null;
  next_match_id: string | null;
  standings: StandingsRow[];
  champions: string[];
  statistics: PlayerStatsRow[];
};

export type OverallStatistics = {
  game_days: number;
  players: PlayerStatsRow[];
};

export type HistoryEntry = {
  id: string;
  game_datetime: string;
  finished_at: string | null;
  champions: string[];
  standings: StandingsRow[];
  matches_played: number;
  goals: number;
};

export type SurveyPlayer = {
  membership_id: string;
  name: string;
  is_virtual: boolean;
  my_rating: number | null;
};

export type Survey = {
  rater_membership_id: string;
  players: SurveyPlayer[];
};
