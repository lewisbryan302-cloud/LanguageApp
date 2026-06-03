import numpy as np
import matplotlib.pyplot as plt


def improved_daily_score(b, c, added, d, a, streak, A=5):
    """
    Improved daily score.

    b      = cards reviewed today
    c      = review goal
    added  = cards added today
    d      = add goal
    a      = cards moved from new to learnt today
    streak = current streak
    A      = learning saturation scale
    """

    review_points = 10 * min(1, b / c) if c > 0 else 0
    add_points = 5 * min(1, added / d) if d > 0 else 0
    learning_points = 20 * (1 - np.exp(-a / A)) if A > 0 else 0
    streak_bonus = 5 * np.log1p(streak)

    return review_points + add_points + learning_points + streak_bonus


def simulate_one_user(
    days=180,
    initial_deck_size=0,
    daily_review_goal=50,
    daily_add_goal=10,
    review_noise=4,
    add_noise=2,
    learning_probability=0.6,
    learning_saturation=5,
    streak_protection_probability=0.75,
    review_close_fraction=0.8,
    add_close_fraction=0.8,
    seed=1
):
    """
    Simulates one user.

    streak_protection_probability:
        Probability that a user tops up their activity if they are close
        to maintaining their streak.

    review_close_fraction:
        If reviews_done >= review_close_fraction * daily_review_goal,
        the user is considered close enough to try to finish the review goal.

    add_close_fraction:
        If cards_added >= add_close_fraction * daily_add_goal,
        the user is considered close enough to try to finish the add goal.
    """

    rng = np.random.default_rng(seed)

    scores = []
    deck_sizes = []
    reviews_done = []
    cards_added = []
    cards_learnt = []
    streaks = []

    N = initial_deck_size
    streak = 0

    for day in range(1, days + 1):

        # Initial natural activity
        b = max(0, int(rng.normal(daily_review_goal, review_noise)))
        added = max(0, int(rng.normal(daily_add_goal, add_noise)))

        # -------------------------------------------------------
        # Streak-protection behaviour
        # -------------------------------------------------------
        # If the user is close to the review goal, they may do the
        # extra reviews needed to maintain their streak.
        close_to_review_goal = b >= review_close_fraction * daily_review_goal
        below_review_goal = b < daily_review_goal

        if close_to_review_goal and below_review_goal:
            if rng.random() < streak_protection_probability:
                b = daily_review_goal

        # If the user is close to the add goal, they may add the
        # extra cards needed to maintain their streak.
        close_to_add_goal = added >= add_close_fraction * daily_add_goal
        below_add_goal = added < daily_add_goal

        if close_to_add_goal and below_add_goal:
            if rng.random() < streak_protection_probability:
                added = daily_add_goal

        # Update deck size after adding new cards
        N += added

        # Simulate how many reviewed cards moved from new to learnt today
        a = rng.binomial(n=b, p=learning_probability)

        # Update streak
        if b >= daily_review_goal and added >= daily_add_goal:
            streak += 1
        else:
            streak = 0

        score = improved_daily_score(
            b=b,
            c=daily_review_goal,
            added=added,
            d=daily_add_goal,
            a=a,
            streak=streak,
            A=learning_saturation
        )

        scores.append(score)
        deck_sizes.append(N)
        reviews_done.append(b)
        cards_added.append(added)
        cards_learnt.append(a)
        streaks.append(streak)

    return {
        "scores": np.array(scores),
        "deck_sizes": np.array(deck_sizes),
        "reviews_done": np.array(reviews_done),
        "cards_added": np.array(cards_added),
        "cards_learnt": np.array(cards_learnt),
        "streaks": np.array(streaks),
    }


def simulate_many_users(
    num_users=20,
    days=365,
    base_review_goal=50,
    base_add_goal=10,
    seed=1
):
    """
    Simulates many users with slightly different habits.

    Some users are more consistent, some review more, some add more,
    and some have higher learning probability.
    """

    rng = np.random.default_rng(seed)

    all_user_results = []

    for user_id in range(num_users):

        # Each user gets slightly different behaviour
        user_review_goal = max(1, int(rng.normal(base_review_goal, 10)))
        user_add_goal = max(1, int(rng.normal(base_add_goal, 3)))

        review_noise = rng.uniform(3, 12)
        add_noise = rng.uniform(1, 5)
        learning_probability = rng.uniform(0.45, 0.8)

        user_results = simulate_one_user(
            days=days,
            initial_deck_size=0,
            daily_review_goal=user_review_goal,
            daily_add_goal=user_add_goal,
            review_noise=review_noise,
            add_noise=add_noise,
            learning_probability=learning_probability,
            learning_saturation=5,
            streak_protection_probability=0.75,
            review_close_fraction=0.8,
            add_close_fraction=0.8,
            seed=seed + user_id
        )

        user_results["user_id"] = user_id + 1
        user_results["review_goal"] = user_review_goal
        user_results["add_goal"] = user_add_goal
        user_results["learning_probability"] = learning_probability

        all_user_results.append(user_results)

    return all_user_results


def calculate_weekly_leaderboard_scores(all_user_results, days_per_week=7):
    """
    Calculates weekly raw scores, leaderboard placements,
    bonus multipliers, and boosted weekly scores.
    """

    num_users = len(all_user_results)
    days = len(all_user_results[0]["scores"])
    num_weeks = days // days_per_week

    raw_weekly_scores = np.zeros((num_weeks, num_users))
    boosted_weekly_scores = np.zeros((num_weeks, num_users))
    placements = np.zeros((num_weeks, num_users), dtype=int)
    multipliers = np.ones((num_weeks, num_users))

    for week in range(num_weeks):
        start = week * days_per_week
        end = start + days_per_week

        for user_index, user_results in enumerate(all_user_results):
            raw_weekly_scores[week, user_index] = np.sum(user_results["scores"][start:end])

        # Rank users by raw weekly score, highest first
        ranked_indices = np.argsort(raw_weekly_scores[week])[::-1]

        for place, user_index in enumerate(ranked_indices, start=1):
            placements[week, user_index] = place

            if place == 1:
                multipliers[week, user_index] = 2.0
            elif place == 2:
                multipliers[week, user_index] = 1.5
            elif place == 3:
                multipliers[week, user_index] = 1.2
            else:
                multipliers[week, user_index] = 1.0

        boosted_weekly_scores[week] = raw_weekly_scores[week] * multipliers[week]

    cumulative_raw_scores = np.cumsum(raw_weekly_scores, axis=0)
    cumulative_boosted_scores = np.cumsum(boosted_weekly_scores, axis=0)

    return {
        "raw_weekly_scores": raw_weekly_scores,
        "boosted_weekly_scores": boosted_weekly_scores,
        "placements": placements,
        "multipliers": multipliers,
        "cumulative_raw_scores": cumulative_raw_scores,
        "cumulative_boosted_scores": cumulative_boosted_scores,
    }


# -----------------------------
# Run multi-user simulation
# -----------------------------

num_users = 20
days = 365

all_user_results = simulate_many_users(
    num_users=num_users,
    days=days,
    base_review_goal=50,
    base_add_goal=10,
    seed=1
)

leaderboard_results = calculate_weekly_leaderboard_scores(
    all_user_results,
    days_per_week=7
)

weeks = np.arange(1, leaderboard_results["raw_weekly_scores"].shape[0] + 1)


# -----------------------------
# Print final summary
# -----------------------------

final_raw_scores = leaderboard_results["cumulative_raw_scores"][-1]
final_boosted_scores = leaderboard_results["cumulative_boosted_scores"][-1]

raw_ranking = np.argsort(final_raw_scores)[::-1]
boosted_ranking = np.argsort(final_boosted_scores)[::-1]

print("\nFinal ranking WITHOUT weekly bonuses:")
for place, user_index in enumerate(raw_ranking, start=1):
    print(
        f"{place:2d}. User {user_index + 1:2d} "
        f"- raw score = {final_raw_scores[user_index]:.1f}"
    )

print("\nFinal ranking WITH weekly leaderboard bonuses:")
for place, user_index in enumerate(boosted_ranking, start=1):
    print(
        f"{place:2d}. User {user_index + 1:2d} "
        f"- boosted score = {final_boosted_scores[user_index]:.1f} "
        f"- raw score = {final_raw_scores[user_index]:.1f}"
    )


# -----------------------------
# Plot top users: raw vs boosted
# -----------------------------

top_users = boosted_ranking[:5]

plt.figure(figsize=(10, 5))

for user_index in top_users:
    plt.plot(
        weeks,
        leaderboard_results["cumulative_raw_scores"][:, user_index],
        linestyle="--",
        label=f"User {user_index + 1} raw"
    )

    plt.plot(
        weeks,
        leaderboard_results["cumulative_boosted_scores"][:, user_index],
        label=f"User {user_index + 1} boosted"
    )

plt.xlabel("Week")
plt.ylabel("Cumulative score")
plt.title("Cumulative raw vs boosted scores for top users")
plt.legend()
plt.grid(True)
plt.savefig("leaderboard_raw_vs_boosted.png", dpi=200, bbox_inches="tight")


# -----------------------------
# Plot weekly multipliers for top users
# -----------------------------

plt.figure(figsize=(10, 5))

for user_index in top_users:
    plt.plot(
        weeks,
        leaderboard_results["multipliers"][:, user_index],
        marker="o",
        label=f"User {user_index + 1}"
    )

plt.xlabel("Week")
plt.ylabel("Weekly multiplier")
plt.title("Weekly leaderboard multipliers for top users")
plt.yticks([1.0, 1.2, 1.5, 2.0])
plt.legend()
plt.grid(True)
plt.savefig("weekly_leaderboard_multipliers.png", dpi=200, bbox_inches="tight")


# -----------------------------
# Plot score inflation from bonuses
# -----------------------------

total_raw_by_week = np.sum(leaderboard_results["raw_weekly_scores"], axis=1)
total_boosted_by_week = np.sum(leaderboard_results["boosted_weekly_scores"], axis=1)

plt.figure(figsize=(10, 5))
plt.plot(weeks, total_raw_by_week, label="Total raw weekly score")
plt.plot(weeks, total_boosted_by_week, label="Total boosted weekly score")
plt.xlabel("Week")
plt.ylabel("Total score awarded")
plt.title("Weekly score inflation caused by leaderboard bonuses")
plt.legend()
plt.grid(True)
plt.savefig("weekly_score_inflation.png", dpi=200, bbox_inches="tight")


print("\nPlots created.")
print("Saved images:")
print(" - leaderboard_raw_vs_boosted.png")
print(" - weekly_leaderboard_multipliers.png")
print(" - weekly_score_inflation.png")

plt.show(block=True)

input("Press Enter to close...")