import numpy as np
import matplotlib.pyplot as plt


def daily_score(c, d, s, a, b, N, y):
    """
    Score formula:
    c + d + s + max(1, a) * (1 + (b/N)**(1/y))
    """
    if N <= 0:
        raise ValueError("Deck size N must be positive.")
    if y <= 0:
        raise ValueError("y must be positive.")

    return c + d + s + max(1, a) * (1 + (b / N) ** (1 / y))


def simulate_scores(
    days=100,
    initial_deck_size=100,
    daily_review_goal=20,
    daily_add_goal=5,
    y=2,
    review_noise=5,
    add_noise=2,
    learning_probability=0.7,
    seed=42
):
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

        # Simulate how many cards you reviewed today
        b = max(0, int(rng.normal(daily_review_goal, review_noise)))

        # Simulate how many new cards you added today
        added = max(0, int(rng.normal(daily_add_goal, add_noise)))

        # Simulate how many new cards moved to learnt today
        # This is limited by how many reviews happened
        a = rng.binomial(n=b, p=learning_probability)

        # Update deck size
        N += added

        # Update streak:
        # Here, a successful day means you reviewed at least c cards
        # and added at least d cards.
        if b >= daily_review_goal and added >= daily_add_goal:
            streak += 1
        else:
            streak = 0

        score = daily_score(
            c=daily_review_goal,
            d=daily_add_goal,
            s=streak,
            a=a,
            b=b,
            N=N,
            y=y
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


# Run simulation
results = simulate_scores(
    days=120,
    initial_deck_size=200,
    daily_review_goal=30,
    daily_add_goal=5,
    y=2,
    review_noise=8,
    add_noise=2,
    learning_probability=0.6,
    seed=1
)

days = np.arange(1, len(results["scores"]) + 1)

# Plot score over time
plt.figure(figsize=(10, 5))
plt.plot(days, results["scores"])
plt.xlabel("Day")
plt.ylabel("Daily score")
plt.title("Score evolution over time")
plt.grid(True)
plt.show()

# Plot important components
plt.figure(figsize=(10, 5))
plt.plot(days, results["reviews_done"], label="Cards reviewed today, b")
plt.plot(days, results["cards_added"], label="Cards added today")
plt.plot(days, results["cards_learnt"], label="New cards learnt today, a")
plt.plot(days, results["streaks"], label="Streak, s")
plt.xlabel("Day")
plt.ylabel("Count")
plt.title("Daily activity components")
plt.legend()
plt.grid(True)
plt.show()

# Plot deck size
plt.figure(figsize=(10, 5))
plt.plot(days, results["deck_sizes"])
plt.xlabel("Day")
plt.ylabel("Deck size, N")
plt.title("Deck size over time")
plt.grid(True)
plt.show()