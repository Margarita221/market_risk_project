CREATE OR REPLACE FUNCTION riskapp_normalize_currency(p_currency text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE UPPER(COALESCE(TRIM(p_currency), ''))
        WHEN 'SUR' THEN 'RUB'
        ELSE UPPER(COALESCE(TRIM(p_currency), ''))
    END;
$$;

CREATE OR REPLACE FUNCTION riskapp_get_latest_exchange_rate(p_from_currency text, p_to_currency text)
RETURNS numeric
LANGUAGE plpgsql
AS $$
DECLARE
    source_currency text := riskapp_normalize_currency(p_from_currency);
    target_currency text := riskapp_normalize_currency(p_to_currency);
    direct_rate numeric;
    source_to_rub numeric;
    rub_to_target numeric;
BEGIN
    IF source_currency = target_currency THEN
        RETURN 1;
    END IF;

    SELECT er.rate
    INTO direct_rate
    FROM exchange_rate AS er
    WHERE er.from_currency = source_currency
      AND er.to_currency = target_currency
    ORDER BY er.rate_date DESC, er.updated_at DESC
    LIMIT 1;

    IF direct_rate IS NOT NULL THEN
        RETURN direct_rate;
    END IF;

    SELECT 1 / er.rate
    INTO direct_rate
    FROM exchange_rate AS er
    WHERE er.from_currency = target_currency
      AND er.to_currency = source_currency
    ORDER BY er.rate_date DESC, er.updated_at DESC
    LIMIT 1;

    IF direct_rate IS NOT NULL THEN
        RETURN direct_rate;
    END IF;

    IF source_currency <> 'RUB' AND target_currency <> 'RUB' THEN
        source_to_rub := riskapp_get_latest_exchange_rate(source_currency, 'RUB');
        rub_to_target := riskapp_get_latest_exchange_rate('RUB', target_currency);
        IF source_to_rub IS NOT NULL AND rub_to_target IS NOT NULL THEN
            RETURN source_to_rub * rub_to_target;
        END IF;
    END IF;

    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_recalculate_portfolio_value(p_portfolio_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE portfolio AS p
    SET
        current_value = COALESCE((
            SELECT SUM(
                pp.quantity * i.current_price * COALESCE(
                    riskapp_get_latest_exchange_rate(i.currency, p.base_currency),
                    0
                )
            )
            FROM portfolio_position AS pp
            JOIN instrument AS i ON i.id = pp.instrument_id
            WHERE pp.portfolio_id = p_portfolio_id
        ), 0),
        updated_at = CURRENT_TIMESTAMP
    WHERE p.id = p_portfolio_id;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_refresh_portfolio_value_from_position()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM riskapp_recalculate_portfolio_value(OLD.portfolio_id);
        RETURN OLD;
    END IF;

    PERFORM riskapp_recalculate_portfolio_value(NEW.portfolio_id);

    IF TG_OP = 'UPDATE' AND OLD.portfolio_id IS DISTINCT FROM NEW.portfolio_id THEN
        PERFORM riskapp_recalculate_portfolio_value(OLD.portfolio_id);
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_refresh_portfolios_from_instrument_price()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    affected_portfolio_id bigint;
BEGIN
    IF NEW.current_price IS DISTINCT FROM OLD.current_price THEN
        FOR affected_portfolio_id IN
            SELECT DISTINCT pp.portfolio_id
            FROM portfolio_position AS pp
            WHERE pp.instrument_id = NEW.id
        LOOP
            PERFORM riskapp_recalculate_portfolio_value(affected_portfolio_id);
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_refresh_portfolio_value_from_portfolio()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.base_currency IS DISTINCT FROM OLD.base_currency THEN
        PERFORM riskapp_recalculate_portfolio_value(NEW.id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_refresh_portfolios_from_exchange_rate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    affected_portfolio_id bigint;
BEGIN
    FOR affected_portfolio_id IN
        SELECT p.id
        FROM portfolio AS p
        WHERE EXISTS (
            SELECT 1
            FROM portfolio_position AS pp
            JOIN instrument AS i ON i.id = pp.instrument_id
            WHERE pp.portfolio_id = p.id
              AND (
                  riskapp_normalize_currency(i.currency) IN (
                      riskapp_normalize_currency(COALESCE(NEW.from_currency, OLD.from_currency)),
                      riskapp_normalize_currency(COALESCE(NEW.to_currency, OLD.to_currency))
                  )
                  OR riskapp_normalize_currency(p.base_currency) IN (
                      riskapp_normalize_currency(COALESCE(NEW.from_currency, OLD.from_currency)),
                      riskapp_normalize_currency(COALESCE(NEW.to_currency, OLD.to_currency))
                  )
              )
        )
    LOOP
        PERFORM riskapp_recalculate_portfolio_value(affected_portfolio_id);
    END LOOP;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_validate_scenario_owner()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM portfolio AS p
        WHERE p.id = NEW.portfolio_id
          AND p.user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION 'Scenario user must match portfolio owner'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION riskapp_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;
