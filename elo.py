import math

K_FACTOR_LOW = 40
K_FACTOR_MID = 20
K_FACTOR_HIGH = 10

def get_k_factor(rating):
    if rating < 2100:
        return K_FACTOR_LOW
    elif rating < 2400:
        return K_FACTOR_MID
    else:
        return K_FACTOR_HIGH

def expected_score(rating1, rating2):
    """Calculate the expected score of player 1 against player 2."""
    return 1 / (1 + math.pow(10, (rating2 - rating1) / 400))

def calculate_elo_change(rating1, rating2, score1):
    """
    Calculate the new Elo ratings for two players.
    :param rating1: Player 1's current rating
    :param rating2: Player 2's current rating
    :param score1: Player 1's score (1 for win, 0.5 for draw, 0 for loss)
    :return: A tuple of the rating change for player 1 and player 2.
    """
    e1 = expected_score(rating1, rating2)
    k1 = get_k_factor(rating1)
    
    rating1_change = k1 * (score1 - e1)
    
    return round(rating1_change), round(-rating1_change)
