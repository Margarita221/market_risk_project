from django.urls import path

from riskapp import clean_views, views


app_name = "riskapp"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("admin/", views.administrator_dashboard, name="administrator_dashboard"),
    path("admin/users/<int:user_id>/toggle/", views.administrator_toggle_user, name="administrator_toggle_user"),
    path("admin/users/<int:user_id>/delete/", views.administrator_delete_user, name="administrator_delete_user"),
    path("admin/portfolios/<int:portfolio_id>/delete/", views.administrator_delete_portfolio, name="administrator_delete_portfolio"),
    path("admin/scenarios/<int:scenario_id>/delete/", views.administrator_delete_scenario, name="administrator_delete_scenario"),
    path("language/<str:language>/", views.switch_language, name="switch_language"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/profile/", views.profile, name="profile"),
    path("accounts/activation-sent/", views.activation_sent, name="activation_sent"),
    path("accounts/activate/<uidb64>/<token>/", views.activate_account, name="activate_account"),
    path("instruments/", views.instrument_list, name="instruments"),
    path("portfolios/", views.portfolio_list, name="portfolios"),
    path("portfolios/create/", views.portfolio_create, name="portfolio_create"),
    path("portfolios/<int:portfolio_id>/", views.portfolio_detail, name="portfolio_detail"),
    path("portfolios/<int:portfolio_id>/edit/", views.portfolio_update, name="portfolio_update"),
    path("portfolios/<int:portfolio_id>/delete/", views.portfolio_delete, name="portfolio_delete"),
    path("portfolios/<int:portfolio_id>/positions/add/", views.portfolio_add_position, name="portfolio_add_position"),
    path("portfolios/<int:portfolio_id>/operations/", views.portfolio_operations, name="portfolio_operations"),
    path("portfolios/<int:portfolio_id>/operations/create/", views.portfolio_operation_create, name="portfolio_operation_create"),
    path("portfolios/<int:portfolio_id>/scenarios/run/", views.portfolio_scenario_run, name="portfolio_scenario_run"),
    path(
        "portfolios/<int:portfolio_id>/positions/<int:position_id>/update/",
        views.portfolio_position_update,
        name="portfolio_position_update",
    ),
    path(
        "portfolios/<int:portfolio_id>/positions/<int:position_id>/delete/",
        views.portfolio_position_delete,
        name="portfolio_position_delete",
    ),
    path("scenarios/", views.scenario_list, name="scenarios"),
    path("scenarios/create/", views.scenario_create, name="scenario_create"),
    path("scenarios/<int:scenario_id>/edit/", views.scenario_update, name="scenario_update"),
    path("scenarios/<int:scenario_id>/delete/", views.scenario_delete, name="scenario_delete"),
    path("scenarios/<int:scenario_id>/run/", views.run_scenario, name="run_scenario"),
    path("results/", views.result_list, name="results"),
    path("results/<int:result_id>/", clean_views.result_detail, name="result_detail"),
    path("results/<int:result_id>/export/<str:report_format>/", clean_views.result_export, name="result_export"),
    path("results/<int:result_id>/delete/", views.result_delete, name="result_delete"),
    path("strategies/compare/", clean_views.strategy_compare, name="strategy_compare"),
    path("strategies/compare/export/<str:report_format>/", clean_views.strategy_compare_export, name="strategy_compare_export"),
]
