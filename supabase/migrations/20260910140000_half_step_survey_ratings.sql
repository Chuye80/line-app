-- Allow half-step ratings in the player survey.
--
-- Ratings were `smallint` constrained to 1..5, so the survey could only
-- express whole stars while `memberships.rating` - the value the survey
-- averages into - is already `numeric` and routinely holds figures like 3.4.
-- Widening the response column lets a rater say "three and a half" rather
-- than being forced to round in their head before the average even happens.
--
-- Existing whole-number responses convert to numeric unchanged, so this is
-- non-destructive.

alter table public.rating_survey_responses
  drop constraint if exists rating_survey_responses_range;

alter table public.rating_survey_responses
  alter column rating type numeric(2, 1) using rating::numeric(2, 1);

-- 1.0 to 5.0 inclusive, and only on the half step: doubling a permitted value
-- always lands on a whole number.
alter table public.rating_survey_responses
  add constraint rating_survey_responses_range
  check (rating >= 1 and rating <= 5 and (rating * 2) = floor(rating * 2));
