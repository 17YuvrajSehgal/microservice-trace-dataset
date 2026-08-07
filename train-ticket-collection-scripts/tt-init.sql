-- StrataTrace: per-service databases in the shared MySQL. ddl-auto=update makes the
-- services auto-create their tables in these (initially empty) databases.
CREATE DATABASE IF NOT EXISTS `ts-assurance-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-auth-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-config-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-consign-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-consign-price-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-contacts-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-food-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-inside-payment-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-notification-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-order-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-order-other-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-payment-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-price-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-route-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-security-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-station-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-train-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-travel-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-travel2-mysql`;
CREATE DATABASE IF NOT EXISTS `ts-user-mysql`;
