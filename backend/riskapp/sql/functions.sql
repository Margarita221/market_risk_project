CREATE OR REPLACE FUNCTION riskapp_recalculate_portfolio_value(p_portfolio_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE portfolio AS p
    SET
        current_value = COALESCE((
            SELECT SUM(pp.quantity * i.current_price)
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
