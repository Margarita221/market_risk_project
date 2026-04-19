DROP TRIGGER IF EXISTS trg_portfolio_position_refresh_portfolio_value ON portfolio_position;
CREATE TRIGGER trg_portfolio_position_refresh_portfolio_value
AFTER INSERT OR UPDATE OR DELETE ON portfolio_position
FOR EACH ROW
EXECUTE FUNCTION riskapp_refresh_portfolio_value_from_position();

DROP TRIGGER IF EXISTS trg_instrument_refresh_portfolio_values ON instrument;
CREATE TRIGGER trg_instrument_refresh_portfolio_values
AFTER UPDATE OF current_price ON instrument
FOR EACH ROW
EXECUTE FUNCTION riskapp_refresh_portfolios_from_instrument_price();

DROP TRIGGER IF EXISTS trg_scenario_validate_owner ON scenario;
CREATE TRIGGER trg_scenario_validate_owner
BEFORE INSERT OR UPDATE OF user_id, portfolio_id ON scenario
FOR EACH ROW
EXECUTE FUNCTION riskapp_validate_scenario_owner();

DROP TRIGGER IF EXISTS trg_portfolio_touch_updated_at ON portfolio;
CREATE TRIGGER trg_portfolio_touch_updated_at
BEFORE UPDATE ON portfolio
FOR EACH ROW
EXECUTE FUNCTION riskapp_touch_updated_at();

DROP TRIGGER IF EXISTS trg_scenario_touch_updated_at ON scenario;
CREATE TRIGGER trg_scenario_touch_updated_at
BEFORE UPDATE ON scenario
FOR EACH ROW
EXECUTE FUNCTION riskapp_touch_updated_at();
