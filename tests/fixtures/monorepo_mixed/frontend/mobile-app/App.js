import React, { useEffect, useState } from 'react';
import {
    SafeAreaView,
    ScrollView,
    StatusBar,
    StyleSheet,
    Text,
    View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';

// Local imports
import HomeScreen from './screens/HomeScreen';
import UserScreen from './screens/UserScreen';
import { ApiService } from './services/ApiService';
import { StorageService } from './services/StorageService';

const Stack = createStackNavigator();

function App() {
    const [isConnected, setIsConnected] = useState(true);
    
    useEffect(() => {
        // Subscribe to network state updates
        const unsubscribe = NetInfo.addEventListener(state => {
            setIsConnected(state.isConnected);
        });

        // Initialize services
        ApiService.initialize();
        StorageService.initialize();

        return unsubscribe;
    }, []);

    return (
        <NavigationContainer>
            <StatusBar barStyle="dark-content" />
            <Stack.Navigator initialRouteName="Home">
                <Stack.Screen name="Home" component={HomeScreen} />
                <Stack.Screen name="User" component={UserScreen} />
            </Stack.Navigator>
            {!isConnected && (
                <View style={styles.offlineBanner}>
                    <Text style={styles.offlineText}>No Internet Connection</Text>
                </View>
            )}
        </NavigationContainer>
    );
}

const styles = StyleSheet.create({
    offlineBanner: {
        backgroundColor: '#ff6b6b',
        padding: 10,
        position: 'absolute',
        bottom: 0,
        width: '100%',
    },
    offlineText: {
        color: 'white',
        textAlign: 'center',
    },
});

export default App;