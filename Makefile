test:
	g++ -std=c++17 -Wall -Wextra -I sim/wokwi tests/test_alert_logic.cpp -o tests/test_alert && ./tests/test_alert
