import QtQuick 1.1
import com.nokia.meego 1.0

// map, ui, POI, navigation, network, debug


IconGridPage {
    model : ListModel {
        id : testModel
        ListElement {
            caption : "Foot"
            icon : "foot.png"
            menu : ""
        }
        ListElement {
            caption : "Car"
            icon : "car.png"
            menu : ""
        }
        ListElement {
            caption : "Cycle"
            icon : "cycle.png"
            menu : ""
        }
        ListElement {
            caption : "Bus"
            icon : "bus.png"
            menu : ""
        }
        ListElement {
            caption : "Train"
            icon : "train.png"
            menu : ""
        }
    }
}