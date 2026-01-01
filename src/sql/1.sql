CREATE DATABASE IF NOT EXISTS `proarb`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `proarb`;

CREATE TABLE IF NOT EXISTS `raw_results` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

  `time` DATETIME(6) NOT NULL,

  `event_title` VARCHAR(512) NOT NULL,
  `market_title` VARCHAR(512) NOT NULL,

  `event_id` VARCHAR(128) NOT NULL,
  `market_id` VARCHAR(128) NOT NULL,

  `yes_price` DOUBLE NULL,
  `no_price` DOUBLE NULL,

  `yes_token_id` VARCHAR(128) NULL,
  `no_token_id` VARCHAR(128) NULL,

  `yes_bid_price_1` DOUBLE NULL,
  `yes_bid_price_size_1` DOUBLE NULL,
  `yes_bid_price_2` DOUBLE NULL,
  `yes_bid_price_size_2` DOUBLE NULL,
  `yes_bid_price_3` DOUBLE NULL,
  `yes_bid_price_size_3` DOUBLE NULL,

  `yes_ask_price_1` DOUBLE NULL,
  `yes_ask_price_1_size` DOUBLE NULL,
  `yes_ask_price_2` DOUBLE NULL,
  `yes_ask_price_2_size` DOUBLE NULL,
  `yes_ask_price_3` DOUBLE NULL,
  `yes_ask_price_3_size` DOUBLE NULL,

  `no_bid_price_1` DOUBLE NULL,
  `no_bid_price_size_1` DOUBLE NULL,
  `no_bid_price_2` DOUBLE NULL,
  `no_bid_price_size_2` DOUBLE NULL,
  `no_bid_price_3` DOUBLE NULL,
  `no_bid_price_size_3` DOUBLE NULL,

  `no_ask_price_1` DOUBLE NULL,
  `no_ask_price_1_size` DOUBLE NULL,
  `no_ask_price_2` DOUBLE NULL,
  `no_ask_price_2_size` DOUBLE NULL,
  `no_ask_price_3` DOUBLE NULL,
  `no_ask_price_3_size` DOUBLE NULL,

  `asset` VARCHAR(32) NOT NULL,
  `spot` DOUBLE NULL,

  `inst_k1` VARCHAR(128) NULL,
  `inst_k2` VARCHAR(128) NULL,

  `k1_strike` DOUBLE NULL,
  `k2_strike` DOUBLE NULL,
  `K_poly` DOUBLE NULL,

  `k1_bid_btc` DOUBLE NULL,
  `k1_ask_btc` DOUBLE NULL,
  `k2_bid_btc` DOUBLE NULL,
  `k2_ask_btc` DOUBLE NULL,
  `k1_mid_btc` DOUBLE NULL,
  `k2_mid_btc` DOUBLE NULL,

  `k1_bid_usd` DOUBLE NULL,
  `k1_ask_usd` DOUBLE NULL,
  `k2_bid_usd` DOUBLE NULL,
  `k2_ask_usd` DOUBLE NULL,
  `k1_mid_usd` DOUBLE NULL,
  `k2_mid_usd` DOUBLE NULL,

  `k1_iv` DOUBLE NULL,
  `k2_iv` DOUBLE NULL,
  `spot_iv_lower` JSON NULL,
  `spot_iv_upper` JSON NULL,
  `k1_fee_approx` DOUBLE NULL,
  `k2_fee_approx` DOUBLE NULL,
  `mark_iv` DOUBLE NULL,

  `k1_expiration_timestamp` DOUBLE NULL,
  `T` DOUBLE NULL,
  `days_to_expairy` DOUBLE NULL,
  `r` DOUBLE NULL,
  `deribit_prob` DOUBLE NULL,

  `k1_ask_1_usd` JSON NULL,
  `k1_ask_2_usd` JSON NULL,
  `k1_ask_3_usd` JSON NULL,
  `k2_ask_1_usd` JSON NULL,
  `k2_ask_2_usd` JSON NULL,
  `k2_ask_3_usd` JSON NULL,

  `k1_bid_1_usd` JSON NULL,
  `k1_bid_2_usd` JSON NULL,
  `k1_bid_3_usd` JSON NULL,
  `k2_bid_1_usd` JSON NULL,
  `k2_bid_2_usd` JSON NULL,
  `k2_bid_3_usd` JSON NULL,

  PRIMARY KEY (`id`),

  INDEX `idx_time` (`time`),
  INDEX `idx_event_market` (`event_id`, `market_id`),
  INDEX `idx_asset_time` (`asset`, `time`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE utf8mb4_0900_ai_ci;