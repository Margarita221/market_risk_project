DROP VIEW IF EXISTS scenario_result_summary;
DROP VIEW IF EXISTS portfolio_position_summary;
DROP VIEW IF EXISTS portfolio_summary;

DROP TRIGGER IF EXISTS trg_scenario_touch_updated_at ON scenario;
DROP TRIGGER IF EXISTS trg_portfolio_touch_updated_at ON portfolio;
DROP TRIGGER IF EXISTS trg_scenario_validate_owner ON scenario;
DROP TRIGGER IF EXISTS trg_instrument_refresh_portfolio_values ON instrument;
DROP TRIGGER IF EXISTS trg_portfolio_position_refresh_portfolio_value ON portfolio_position;

DROP FUNCTION IF EXISTS riskapp_touch_updated_at();
DROP FUNCTION IF EXISTS riskapp_validate_scenario_owner();
DROP FUNCTION IF EXISTS riskapp_refresh_portfolios_from_instrument_price();
DROP FUNCTION IF EXISTS riskapp_refresh_portfolio_value_from_position();
DROP FUNCTION IF EXISTS riskapp_recalculate_portfolio_value(bigint);
