from django.urls import path

from riskapp import views


app_name = "riskapp"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("language/<str:language>/", views.switch_language, name="switch_language"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/profile/", views.profile, name="profile"),
    path("accounts/activation-sent/", views.activation_sent, name="activation_sent"),
    path("accounts/activate/<uidb64>/<token>/", views.activate_account, name="activate_account"),
    path("portfolios/", views.portfolio_list, name="portfolios"),
    path("portfolios/create/", views.portfolio_create, name="portfolio_create"),
    path("portfolios/<int:portfolio_id>/", views.portfolio_detail, name="portfolio_detail"),
    path("portfolios/<int:portfolio_id>/edit/", views.portfolio_update, name="portfolio_update"),
    path("portfolios/<int:portfolio_id>/delete/", views.portfolio_delete, name="portfolio_delete"),
    path("portfolios/<int:portfolio_id>/positions/add/", views.portfolio_add_position, name="portfolio_add_position"),
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
    path("results/<int:result_id>/", views.result_detail, name="result_detail"),
]
