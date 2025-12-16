import yaml
import time

def main():
    # Load configuration
    with open('config.yaml', 'r') as file:
        config = yaml.safe_load(file)

    print(f"Starting bot: {config['bot']['name']} in mode: {config['bot']['mode']}")

    while True:
        # Placeholder for decision-making and trading logic
        print(f"Bot loop running. Pausing for {config['bot']['loop_seconds']} seconds...")
        time.sleep(config['bot']['loop_seconds'])

if __name__ == '__main__':
    main()
