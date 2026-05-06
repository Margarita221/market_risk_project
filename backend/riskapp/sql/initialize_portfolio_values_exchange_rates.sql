UPDATE portfolio AS p
SET current_value = COALESCE((
    SELECT SUM(
        pp.quantity * i.current_price * COALESCE(
            riskapp_get_latest_exchange_rate(i.currency, p.base_currency),
            0
        )
    )
    FROM portfolio_position AS pp
    JOIN instrument AS i ON i.id = pp.instrument_id
    WHERE pp.portfolio_id = p.id
), 0);
