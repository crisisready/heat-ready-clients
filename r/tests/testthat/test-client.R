test_that("status is unauthenticated and sends the right action", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  captured <- NULL
  httr2::local_mocked_responses(function(req) {
    captured <<- req
    httr2::response_json(200, body = list(status = "ok", systems = list(database = "ok"), daily_update_dlq_depth = 0))
  })
  result <- client$status()
  expect_equal(result$status, "ok")
  sent <- captured$body$data
  expect_equal(sent$action, "status")
})

test_that("list_projects sends credentials and no payload", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  captured <- NULL
  httr2::local_mocked_responses(function(req) {
    captured <<- req
    httr2::response_json(200, body = list(projects = list()))
  })
  client$list_projects()
  sent <- captured$body$data
  expect_equal(sent$username, "alice")
  expect_equal(sent$key, "test-key")
  expect_equal(sent$action, "list-projects")
  expect_null(sent$payload)
})

test_that("get_project_status sends the project_id payload", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  captured <- NULL
  httr2::local_mocked_responses(function(req) {
    captured <<- req
    httr2::response_json(200, body = list(project_id = "2026-demo-nyc-us", status = "active", polygon_count = 188))
  })
  result <- client$get_project_status("2026-demo-nyc-us")
  expect_equal(result$status, "active")
  sent <- captured$body$data
  expect_equal(sent$payload$project_id, "2026-demo-nyc-us")
})

test_that("error response raises a heatready_error with message and code", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  httr2::local_mocked_responses(list(
    httr2::response_json(404, body = list(error = "Project 'nope' not found", code = "project_not_found"))
  ))
  err <- tryCatch(client$get_project_status("nope"), error = function(e) e)
  expect_s3_class(err, "heatready_error")
  expect_equal(err$code, "project_not_found")
  expect_equal(err$status_code, 404)
})

test_that("invalid credentials raise with code invalid_credentials", {
  client <- HeatReadyClient$new(username = "alice", key = "wrong-key", retry_delays = numeric(0))
  httr2::local_mocked_responses(list(
    httr2::response_json(401, body = list(error = "Invalid username or key", code = "invalid_credentials"))
  ))
  err <- tryCatch(client$list_projects(), error = function(e) e)
  expect_s3_class(err, "heatready_error")
  expect_equal(err$code, "invalid_credentials")
})

test_that("retries on 503 then succeeds", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = c(0, 0))
  responses <- list(
    httr2::response_json(503, body = list(error = "Database unavailable", code = "database_unavailable")),
    httr2::response_json(200, body = list(projects = list()))
  )
  httr2::local_mocked_responses(responses)
  result <- client$list_projects()
  expect_equal(length(result$projects), 0)
})

test_that("503 exhausts retries and raises", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = c(0, 0))
  resp <- httr2::response_json(503, body = list(error = "Database unavailable", code = "database_unavailable"))
  httr2::local_mocked_responses(list(resp, resp, resp))
  err <- tryCatch(client$list_projects(), error = function(e) e)
  expect_s3_class(err, "heatready_error")
  expect_equal(err$status_code, 503)
})

test_that("create_project sends the geojson under json_obj", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  captured <- NULL
  httr2::local_mocked_responses(function(req) {
    captured <<- req
    httr2::response_json(202, body = list(project_id = "test-project", status = "initializing", estimated_minutes = 15))
  })
  geojson <- list(type = "FeatureCollection", features = list())
  result <- client$create_project("test-project", geojson)
  expect_equal(result$status, "initializing")
  sent <- captured$body$data
  expect_equal(sent$payload$json_obj$type, "FeatureCollection")
})

test_that("iter_metrics pages through all rows into one data frame", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  page_1 <- list(
    project_id = "p", total_rows = 3, limit = 2, offset = 0,
    metrics = data.frame(name = c("a", "a"), date = c("2026-01-01", "2026-01-02")),
    polygon_coverage = list()
  )
  page_2 <- list(
    project_id = "p", total_rows = 3, limit = 2, offset = 2,
    metrics = data.frame(name = c("a"), date = c("2026-01-03")),
    polygon_coverage = list()
  )
  httr2::local_mocked_responses(list(
    httr2::response_json(200, body = page_1),
    httr2::response_json(200, body = page_2)
  ))
  rows <- client$iter_metrics("p", page_size = 2)
  expect_equal(nrow(rows), 3)
  expect_equal(rows$date, c("2026-01-01", "2026-01-02", "2026-01-03"))
})

test_that("iter_metrics stops on an empty first page", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  httr2::local_mocked_responses(list(
    httr2::response_json(200, body = list(project_id = "p", total_rows = 0, limit = 500, offset = 0,
                                           metrics = list(), polygon_coverage = list()))
  ))
  rows <- client$iter_metrics("p")
  expect_equal(nrow(rows), 0)
})

test_that("get_lst_data omits limit/offset when latest_only is TRUE", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  captured <- NULL
  httr2::local_mocked_responses(function(req) {
    captured <<- req
    httr2::response_json(200, body = list(project_id = "p", lst = list()))
  })
  client$get_lst_data("p", latest_only = TRUE)
  sent <- captured$body$data
  expect_null(sent$payload$limit)
  expect_null(sent$payload$offset)
})

test_that("backfill_lst sends only the days field when composite_prep is omitted", {
  client <- HeatReadyClient$new(username = "alice", key = "test-key", retry_delays = numeric(0))
  captured <- NULL
  httr2::local_mocked_responses(function(req) {
    captured <<- req
    httr2::response_json(202, body = list(project_id = "p", status = "backfilling", message = "..."))
  })
  client$backfill_lst("p", days = 90)
  sent <- captured$body$data
  expect_equal(sent$payload$days, 90)
  expect_null(sent$payload$composite_prep)
})
