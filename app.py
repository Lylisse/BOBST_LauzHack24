import time
import threading
from platform import machine

from gpiozero import LED, Button
from send_data import send_telemetry
from power_consumption import read_sensor_data
from flask import Flask, render_template, Response, jsonify, request
import json
import datetime
from power_consumption import read_sensor_data

app = Flask(__name__)

running = False
boxspeed = 0
count = 0
energy = 0
total_energy = 0
three_second_energy = 0

speedSlider = 100
lasthigh = False
boxStack = []
debut_time = time.time()

time_between_ticks = 0.08
sliderValue = 100

used_pins = {
    0: LED(17),
    1: LED(18),
    2: LED(27),
    3: LED(22),
}

SENSOR_PIN = Button(23)

step_sequence = [
    ["H", "L", "L", "L"],
    ["H", "H", "L", "L"],
    ["L", "H", "L", "L"],
    ["L", "H", "H", "L"],
    ["L", "L", "H", "L"],
    ["L", "L", "H", "H"],
    ["L", "L", "L", "H"],
    ["H", "L", "L", "H"]
]


def rotate_step(direction):
    for step in step_sequence[::direction]:
        for pin in range(4):
            if step[pin] == "H":
                used_pins[pin].on()
            elif step[pin] == "L":
                used_pins[pin].off()
            else:
                raise Exception("Wtf...")
        while sliderValue == 0:
            time.sleep(0.5)
        time.sleep(time_between_ticks / sliderValue)


def run_conveyer():
    while True:
        if running:
            for _ in range(512):
                rotate_step(1)


def isBoxNew():
    global lasthigh
    if not SENSOR_PIN.is_pressed:
        if lasthigh:
            lasthigh = False
            return True
    else:
        lasthigh = True
        return False


def calculate_box_speed(boxstack):
    global boxspeed
    if boxstack[-1] - boxstack[0] == 0:
        boxspeed = 0
        return
    boxspeed = 35.5 / (boxstack[-1] - boxstack[0])


def box_speed_detector():
    if len(boxStack) > 4:
        for i in range(1, len(boxStack)):
            boxStack[i - 1] = boxStack[i]
        boxStack.pop()
    boxStack.append(time.time())


def calculate_box_speed_2():
    global boxspeed
    if SENSOR_PIN.is_pressed:
        current_time = 0
        start_time = time.time()
        while SENSOR_PIN.is_pressed:
            if not running:
                break
            current_time = time.time()
            time.sleep(0.05)
        time_elapsed = current_time - start_time
        boxspeed = 3.7 / time_elapsed * 8.45
    if not running:
        boxspeed = 0

def data_gatherer():
    timer2 = time.time()
    while True:
        if time.time() - timer2 > 1:
            global energy, total_energy, three_second_energy
            energy = read_sensor_data() / 3600
            total_energy += energy
            three_second_energy += energy

        calculate_box_speed_2()
        time.sleep(0.1)

def box_incrementer():
    global count
    timer = time.time()
    while True:
        if isBoxNew():
            if time.time() - timer > 1:
                count += 1
                timer = time.time()
        time.sleep(0.1)


# Serve the HTML page
@app.route('/')
def home():
    return render_template('index.html')


# Endpoint for telemetry data (SSE)
@app.route('/telemetry')
def telemetry():
    def generate_telemetry():
        while True:
            global three_second_energy
            telemetry_data = {
                "telemetry": {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "datasource": "178.197.195.45:80",
                    "machineid": "lauzhack-pi11",
                    "totaloutputunitcount": count,
                    "machineSpeed": boxspeed,
                    "energyConsumption": three_second_energy,
                    "totalEnergyConsumption": total_energy,
                }
            }
            three_second_energy = 0
            yield f"data: {json.dumps(telemetry_data)}\n\n"
            time.sleep(3)

    return Response(generate_telemetry(), content_type='text/event-stream')


# Define the route that will handle the slider data
@app.route('/data', methods=['POST'])
def handle_slider_data():
    data = request.get_json()  # Get the data sent from the frontend
    slider_value = data.get('slider_value')  # Get the slider value

    if slider_value is not None:
        print(f"Received slider value: {slider_value}")
        global sliderValue
        sliderValue = int(slider_value)
        return jsonify({"status": "Slider value received", "slider_value": slider_value})
    else:
        return jsonify({"status": "Error", "message": "No slider value received"}), 400


@app.route('/job-status', methods=['POST'])
def job_status():
    try:
        # Get JSON data sent from the frontend
        data = request.get_json()
        status = data.get('status')
        job_name = data.get('jobName')
        machine_status = data.get('running')

        if status and job_name:
            # You can process the job status here, for example, log it or update a database
            print(f"Job '{job_name}' status: {status}")
            global running
            running = machine_status
            print("machine_status", machine_status)

            # Respond with a success message
            return jsonify({"message": f"Job '{job_name}' {status} successfully"}), 200
        else:
            # If status or jobName is missing, return an error
            return jsonify({"error": "Missing 'status' or 'jobName' in the request"}), 400
    except Exception as e:
        # Catch any exceptions and return an error message
        return jsonify({"error": str(e)}), 500


conveyorthread = threading.Thread(target=run_conveyer)
datathread = threading.Thread(target=data_gatherer)
boxthread = threading.Thread(target=box_incrementer)

# Main entry point
if __name__ == '__main__':
    # Start background threads
    conveyorthread = threading.Thread(target=run_conveyer, daemon=True)
    datathread = threading.Thread(target=data_gatherer, daemon=True)
    boxthread = threading.Thread(target=box_incrementer, daemon=True)

    conveyorthread.start()
    datathread.start()
    boxthread.start()

    # Start Flask server
    app.run(host='0.0.0.0', port=5000)
