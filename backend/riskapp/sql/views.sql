DROP VIEW IF EXISTS scenario_result_summary;
DROP VIEW IF EXISTS portfolio_position_summary;
DROP VIEW IF EXISTS portfolio_summary;

CREATE OR REPLACE VIEW portfolio_summary AS
SELECT
    p.id AS portfolio_id,
    p.user_id,
    p.name AS portfolio_name,
    COUNT(pp.id) AS positions_count,
    p.initial_value,
    p.current_value,
    (p.current_value - p.initial_value) AS profit_loss,
    CASE
        WHEN p.initial_value > 0
            THEN ROUND(((p.current_value - p.initial_value) / p.initial_value) * 100, 4)
        ELSE NULL
    END AS profit_loss_percent,
    p.created_at,
    p.updated_at
FROM portfolio AS p
LEFT JOIN portfolio_position AS pp ON pp.portfolio_id = p.id
GROUP BY p.id, p.user_id, p.name, p.initial_value, p.current_value, p.created_at, p.updated_at;

CREATE OR REPLACE VIEW portfolio_position_summary AS
SELECT
    pp.id AS position_id,
    pp.portfolio_id,
    p.user_id,
    i.id AS instrument_id,
    i.ticker,
    i.name AS instrument_name,
    i.instrument_type,
    i.currency,
    pp.quantity,
    pp.average_purchase_price,
    i.current_price,
    (pp.quantity * pp.average_purchase_price) AS purchase_value,
    (pp.quantity * i.current_price) AS current_value,
    ((pp.quantity * i.current_price) - (pp.quantity * pp.average_purchase_price)) AS profit_loss,
    CASE
        WHEN pp.average_purchase_price > 0
            THEN ROUND(((i.current_price - pp.average_purchase_price) / pp.average_purchase_price) * 100, 4)
        ELSE NULL
    END AS profit_loss_percent,
    pp.created_at
FROM portfolio_position AS pp
JOIN portfolio AS p ON p.id = pp.portfolio_id
JOIN instrument AS i ON i.id = pp.instrument_id;

CREATE OR REPLACE VIEW scenario_result_summary AS
SELECT
    s.id AS scenario_id,
    s.user_id,
    s.portfolio_id,
    p.name AS portfolio_name,
    s.name AS scenario_name,
    s.trend,
    s.volatility,
    s.noise_level,
    s.time_horizon,
    s.time_step,
    s.iterations_count,
    sr.id AS simulation_result_id,
    sr.execution_time,
    sr.expected_return,
    sr.portfolio_volatility,
    sr.final_value,
    sr.max_drawdown,
    sr.status,
    sr.comment
FROM scenario AS s
JOIN portfolio AS p ON p.id = s.portfolio_id
LEFT JOIN simulation_result AS sr ON sr.scenario_id = s.id;
