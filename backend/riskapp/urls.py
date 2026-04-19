from django.urls import path

from riskapp import views


app_name = "riskapp"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("language/<str:language>/", views.switch_language, name="switch_language"),
    path("portfolios/", views.portfolio_list, name="portfolios"),
    path("portfolios/create/", views.portfolio_create, name="portfolio_create"),
    path("portfolios/<int:portfolio_id>/", views.portfolio_detail, name="portfolio_detail"),
    path("portfolios/<int:portfolio_id>/positions/add/", views.portfolio_add_position, name="portfolio_add_position"),
    path("scenarios/", views.scenario_list, name="scenarios"),
    path("scenarios/<int:scenario_id>/run/", views.run_scenario, name="run_scenario"),
    path("results/<int:result_id>/", views.result_detail, name="result_detail"),
]
