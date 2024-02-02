# pico_synth_sandbox-player - Synchronized Audio & MIDI playback
# 2024 Cooper Dalrymple - me@dcdalrymple.com
# GPL v3 License

import pico_synth_sandbox.tasks
from pico_synth_sandbox.board import get_board
from pico_synth_sandbox.tasks import Task
from pico_synth_sandbox.audio import get_audio_driver
from pico_synth_sandbox.midi import Midi
from pico_synth_sandbox.display import Display
from pico_synth_sandbox.encoder import Encoder

import json
import os
import time
import sys
import audiocore
import umidiparser
import asyncio

# Initialize Objects
board = get_board()
audio = get_audio_driver(board)
audio.set_buffer_size(16384)
audio.mute()
midi = Midi(board)
midi.pause() # midi input task is not needed
board.mount_sd_card()

try:
    with open("/sd/player.json", 'r') as file:
        config = json.load(file)
except:
    config = False
if config == False:
    print("Invalid configuration or configuration file not found. Must provide valid /player.json file.")
    sys.exit()

# Data and Path Validation
class Validation:
    def valid_key(data, key):
        return key in data
    def valid_int(value, key="", min=0):
        if len(key) > 0:
            if not Validation.valid_key(value, key):
                return False
            value = value[key]
        return type(value) is type(0) and (not type(min) is type(0) or value > min)
    def valid_float(value, key="", min=0.0):
        if len(key) > 0:
            if not Validation.valid_key(value, key):
                return False
            value = value[key]
        return type(value) is type(0.0) and (not type(min) is type(0.0) or value > min)
    def valid_string(value, key=""):
        if len(key) > 0:
            if not Validation.valid_key(value, key):
                return False
            value = value[key]
        return type(value) is type("") and len(value) > 0
    def valid_list(value, key=""):
        if len(key) > 0:
            if not Validation.valid_key(value, key):
                return False
            value = value[key]
        return type(value) is type([]) and len(value) > 0
    def check_ext(value, ext):
        if type(ext) is type([]):
            for _ext in ext:
                if Song.check_ext(value, _ext):
                    return True
            return False
        if not type(ext) is type(""):
            return False
        if not ext.startswith("."):
                ext = "." + ext
        if len(value) <= len(ext):
            return False
        if not value.lower().endswith(ext.lower()):
            return False
        return True
    def valid_path(value, key="", ext="", check=True, sanitize=True):
        if len(key) > 0:
            if not Validation.valid_key(value, key):
                return False
            value = value[key]
        if not Validation.valid_string(value):
            return False
        if len(ext) > 0 and not Validation.check_ext(value, ext):
            return False
        if check and not Validation.check_path(value, sanitize):
            return False
        return True
    def sanitize_path(path):
        if not path.startswith("/"):
            path = "/" + path
        path = "/sd" + path
        return path
    def check_path(path, sanitize=True):
        if sanitize:
            path = Validation.sanitize_path(path)
        try:
            os.stat(path)
        except:
            return False
        return True
    def basename(path):
        if not Validation.valid_string(path):
            return ""
        return path[path.rfind("/")+1:path.rfind(".")]

class Song:
    def __init__(self, data):
        self.keynum = data["key"]
        self.midi_note = data["notenum"] if Validation.valid_int(data, "notenum") else None
        self.audio_file = Validation.sanitize_path(data["audio"]) if Validation.valid_path(data, "audio", "wav") else None
        self.midi_file = Validation.sanitize_path(data["midi"]) if Validation.valid_path(data, "midi", "mid") else None
        self.title = data["title"] if Validation.valid_string(data, "title") else Validation.basename(self.audio_file if self.audio_file else self.midi_file)
    def valid(data):
        if not type(data) is type({}):
            return False
        if not Validation.valid_int(data, "key"):
            return False
        if not Validation.valid_path(data, "audio", "wav") and not Validation.valid_path(data, "midi", "mid"):
            return False
        return True
    def print(self):
        print("\n:: {} ::".format(self.title))
        print("Key = {:d}".format(self.keynum))
        if self.audio_file:
            print("Audio = {}".format(self.audio_file))
        if self.midi_file:
            print("Midi = {}".format(self.midi_file))
        if self.midi_note:
            print("Midi Note = {:d}".format(self.midi_note))
    def is_key(self, keynum):
        return self.keynum == keynum
    def has_audio(self):
        return not self.audio_file is None
    def has_midi(self):
        return not self.midi_file is None

if Validation.valid_float(config, "volume", False):
    audio.set_level(config["volume"])
if Validation.valid_int(config, "midi_channel"):
    midi.set_channel(config["midi_channel"])

if not Validation.valid_list(config, "songs"):
    print("Must provide list of songs in /player.json.")
    sys.exit()

print("\nAvailable Song Data")
songs = []
for i in range(len(config["songs"])):
    song_data = config["songs"][i]
    if not Song.valid(song_data):
        print("Invalid song configuration at {:d}".format(i))
        continue
    song = Song(song_data)
    song.print()
    songs.append(song)

if len(songs) == 0:
    print("No valid songs available. Please check configuration at /player.json.")
    sys.exit()

selected = 0
level = audio.get_level() # audio level is reset when reconfigured

class SongPlayer(Task):
    def __init__(self, audio, midi):
        self.audio = audio
        self.midi = midi
        self.song = None
        self.audio_file = None
        self.audio_wav = None
        self.audio_playing = False
        self.midi_track = None
        self.midi_playing = False
        self.start_time = 0
        Task.__init__(self, update_frequency=1000)
    def play(self, song):
        self.stop()

        if not isinstance(song, Song):
            return False
        self.song = song
            
        if self.song.has_midi():
            self.midi_track = umidiparser.MidiFile(self.song.midi_file).play(sleep=False)

        if self.song.has_audio():
            self.audio_file = open(self.song.audio_file, "rb")
            self.audio_wav = audiocore.WaveFile(self.audio_file)
            self.audio.configure(
                sample_rate=self.audio_wav.sample_rate,
                channel_count=self.audio_wav.channel_count,
                bits_per_sample=self.audio_wav.bits_per_sample
            )
            global level
            self.audio.set_level(level)
            self.audio.play(self.audio_wav)
            self.audio_playing = True
            
        self.start_time = time.monotonic_ns() // 1000

        return True
    def stop(self):
        self.audio.stop()
        if not self.audio_file is None:
            self.audio_file.close()
            self.audio_file = None
        self.midi_playing = False
        if not self.song is None:
            self.song = None

    def is_playing(self):
        if self.song is None:
            return False
        return True
    
    async def update(self):
        if not self.is_playing():
            return
        
        # Handle all midi file tasks
        if self.song.has_midi() and self.midi_track:
            self.midi_playing = True
            midi_time = 0
            for event in self.midi_track:
                midi_time += event.delta_us
                current_time = time.monotonic_ns() // 1000 - self.start_time
                delay = midi_time - current_time
                if delay > 0:
                    await asyncio.sleep(delay / 1000000)
                if not self.midi_playing:
                    break
                if event.status == umidiparser.NOTE_ON:
                    midi.send_note_on(event.note, event.velocity, event.channel)
                elif event.status == umidiparser.NOTE_OFF:
                    midi.send_note_off(event.note, event.channel)
                elif event.status == umidiparser.CONTROL_CHANGE:
                    midi.send_control_change(event.control, event.value, event.channel)
                elif event.status == umidiparser.PROGRAM_CHANGE:
                    midi.send_program_change(event.program, event.channel)
                # Ignore unrecognized events
            self.midi_playing = False
        
        if self.audio_playing and not self.audio.is_playing():
            self.audio_playing = False
        if not self.midi_playing and not self.audio_playing:
            self.stop()

player = SongPlayer(audio, midi)

display = Display(board)
display.clear()
display.hide_cursor()
display.enable_horizontal_graph()

def update_display():
    global selected, level, display, audio, player
    display.write_horizontal_graph(value=level, position=(0,0), width=15)
    display.write('"' if player.is_playing() else '>', (15,0))
    display.write(songs[selected].title, (0,1))
update_display()

def increment_song():
    global selected, player
    if not player.is_playing():
        selected = (selected + 1) % len(songs)
        update_display()

def decrement_song():
    global selected, player
    if not player.is_playing():
        selected = (selected - 1) % len(songs)
        update_display()

def toggle_song(index=None):
    global selected, player
    if not index is None:
        selected = index % len(songs)
    if player.is_playing():
        player.stop()
    else:
        player.play(songs[selected])
    update_display()

def increment_volume():
    global level, audio
    if level < 1.0:
        level = min(level + 0.05, 1.0)
        audio.set_level(level)
        update_display()
def decrement_volume():
    global level, audio
    if level > 0.0:
        level = max(audio.get_level() - 0.05, 0.0)
        audio.set_level(level)
        update_display()

'''
# Keyboard Control
from pico_synth_sandbox.keyboard import get_keyboard_driver
keyboard = get_keyboard_driver(board, root=1)
def key_press(keynum, notenum, velocity):
    print(keynum)
    if keynum is None:
        return
    for song in songs:
        if not song.is_key(keynum):
            continue
        print(song.title)
        player.play(song)
        break
keyboard.set_key_press(key_press)
'''

if board.num_encoders() == 1:
    encoder = Encoder(board)
    encoder.set_increment(increment_song)
    encoder.set_decrement(decrement_song)
    encoder.set_click(toggle_song)

elif board.num_encoders() > 1:
    encoders = (Encoder(board, 0), Encoder(board, 1))
    encoders[0].set_increment(increment_volume)
    encoders[0].set_decrement(decrement_volume)
    encoders[1].set_increment(increment_song)
    encoders[1].set_decrement(decrement_song)
    encoders[1].set_click(toggle_song)

pico_synth_sandbox.tasks.run()
