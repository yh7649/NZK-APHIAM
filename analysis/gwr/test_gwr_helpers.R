#!/usr/bin/env Rscript
source(file.path("analysis", "R", "gwr_helpers.R"))
needed <- c("dplyr", "lubridate", "sf", "units")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("Missing test packages: ", paste(missing, collapse = ", "), ". Run `make requirements-r`.")
plants <- sf::st_as_sf(data.frame(id=c("a","b"),lon=c(127,128),lat=c(37,37)),coords=c("lon","lat"),crs=4326)|>sf::st_transform(5179)
monitors <- sf::st_as_sf(data.frame(id=c("near","far"),lon=c(127.01,129),lat=c(37,37)),coords=c("lon","lat"),crs=4326)|>sf::st_transform(5179)
x50 <- exponential_exposure(monitors, plants, c(100,50), 50)
stopifnot(x50$exposure[1]>x50$exposure[2], isTRUE(all.equal(exponential_exposure(monitors,plants,c(200,100),50)$exposure,2*x50$exposure)), all(x50$weights>0), ncol(x50$weights)==2L)
x25 <- exponential_exposure(monitors,plants,c(100,50),25)
stopifnot(x25$weights[2,1]<x50$weights[2,1], inherits(try(exponential_exposure(monitors,plants,c(100,NA),50),silent=TRUE),"try-error"), all(is.finite(x50$distances_km)), all(x50$distances_km>=0))
monthly <- expand.grid(monitor_id=c("m1","m2"),month=1:12); monthly$year<-2022; monthly$pollutant<-"NO2"; monthly$value<-10; monthly$value[monthly$monitor_id=="m1"&monthly$month==1]<-20; monthly$hours<-1; monthly$hours[monthly$monitor_id=="m1"&monthly$month==1]<-3; monthly$latitude<-37; monthly$longitude<-127; monthly<-monthly[!(monthly$monitor_id=="m2"&monthly$month>8),]
annual <- weighted_monitor_years(monthly,9L); stopifnot(nrow(annual)==1L,abs(annual$annual_mean_concentration-(170/14))<1e-10)
pm<-expand.grid(plant_id=c("p1","p2"),month=1:12); pm$year<-2022; pm$emissions_pollutant<-"nox"; pm$emissions_kg<-10; pm<-pm[!(pm$plant_id=="p2"&pm$month>8),]
py<-summarise_plant_years(pm,9L); stopifnot(nrow(py)==1L,py$plant_id=="p1")
duplicate<-data.frame(monitor_id=c("m1","m2","m3"),annual_mean_concentration=c(10,20,5),valid_hours=c(1,3,2),projected_x=c(1,1,2),projected_y=c(1,1,2))
collapsed<-collapse_duplicate_sites(duplicate); stopifnot(nrow(collapsed)==2L,collapsed$contributing_monitor_count[collapsed$projected_x==1]==2L,collapsed$annual_mean_concentration[collapsed$projected_x==1]==17.5)
coord_only<-data.frame(monitor_id=c("m1","m2","m3"),year=c(2022,2022,2022),projected_x=c(1,1,2),projected_y=c(1,1,2))
coord_collapsed<-collapse_site_coordinates(coord_only); stopifnot(nrow(coord_collapsed)==2L,coord_collapsed$contributing_monitor_count[coord_collapsed$projected_x==1]==2L,coord_collapsed$contributing_monitor_ids[coord_collapsed$projected_x==1]=="m1;m2")
message("All deterministic GWR helper smoke tests passed.")
