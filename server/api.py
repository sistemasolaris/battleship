from flask import Blueprint, request, session
from flask_login import current_user
from flask_socketio import join_room, leave_room, close_room, emit

from . import socketio
from server.models import User
from server.views import rooms

api = Blueprint("api", __name__)


# Game events

def get_boards(room, user):
    """Retrieves the correct board information for an user in a room
    
    Returns:
        dict: player and opponent's boards
    """
    game =  rooms[room]["game"]
    if user ==  rooms[room]["creator"]["user_id"]:
        return {"player_board": game.player1_board.get_board(),
                "opponent_board": game.player2_board.get_secret_board()}
    elif user == rooms[room]["challenger"]["user_id"]:
        return {"player_board": game.player2_board.get_board(),
                "opponent_board": game.player1_board.get_secret_board()}
    
def get_tile(coords, room, user):
    game = rooms[room]["game"]
    if user == rooms[room]["creator"]["user_id"]:
        return game.player2_board.get_board()[coords[1]][coords[0]]
    if user == rooms[room]["challenger"]["user_id"]:
        return game.player1_board.get_board()[coords[1]][coords[0]]
    
def attack_coords(coords, room, user):
    game = rooms[room]["game"]
    if user == rooms[room]["creator"]["user_id"]:
        return game.player2_board.attack_coordinate([coords[1], coords[0]])
    if user == rooms[room]["challenger"]["user_id"]:
        return game.player1_board.attack_coordinate([coords[1], coords[0]])


# SocketIO events

@socketio.on("connect")
def connect(auth):
    """Handles connection to room and emits a game state update upon connection"""
    room = session.get("room")
    user = current_user.get_id()

    # Check if room exists
    if room is None:
        return
    if room not in rooms:
        leave_room(room)
        return
    
    # Checks if the room is full
    if rooms[room]["members"] == 2:
        return

    join_room(room)
    rooms[room]["members"] += 1

    # Updates creator and challenger information when new user joins room
    if not rooms[room]["creator"]:
        rooms[room]["creator"] = {"user_id": user, "session_id": request.sid}
    elif not rooms[room]["challenger"]:
        rooms[room]["challenger"] = {"user_id": user, "session_id": request.sid}
        creator = rooms[room]["creator"]
        challenger = rooms[room]["challenger"]
        creator_username = User.query.filter_by(id=creator["user_id"]).first().username
        challenger_username = User.query.filter_by(id=challenger["user_id"]).first().username
        emit("getOpponent", creator_username, to=challenger["session_id"])
        emit("getOpponent", challenger_username, to=creator["session_id"])

    emit("getBoards", get_boards(room, user), to=request.sid)

@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    leave_room(room)

    if room in rooms:
        rooms[room]["members"] -= 1
        if rooms[room]["members"] <= 0:
            del rooms[room]

@socketio.on("attack")
def attack(coords):
    """Handles game attacks"""
    coords = list(map(lambda coord: int(coord), coords)) # Converts coords into integers

    if coords[0] < 0 or coords[0] > 9 or coords[1] < 0 or coords[1] > 9: # Checks for valid coords
        return
    
    room = session.get("room")
    user = current_user.get_id()
    game = rooms[room]["game"]
    creator = rooms[room]["creator"]
    challenger = rooms[room]["challenger"]
    target = None

    if not creator or not challenger: # Wait until all users are connected to room
        return

    # Checks if it is user's turn
    if game.turn % 2 == 1 and user == creator["user_id"]:
        if not attack_coords(coords, room, user):
            return
        target = challenger["session_id"]
        game.increment_turn()
    elif game.turn % 2 == 0 and user == challenger["user_id"]:
        if not attack_coords(coords, room, user):
            return
        target = creator["session_id"]
        game.increment_turn()
    else:
        return

    # Updates the boards
    emit("update", {"target": False, "coords": coords, "status": get_tile(coords, room, user)},
         to=request.sid)
    emit("update", {"target": True, "coords": coords, "status": get_tile(coords, room, user)},
         to=target)
    
    # Checks if the game is over
    if game.is_game_over():
        emit("gameover", current_user.username, to=room)
        close_room(room)
        del rooms[room]