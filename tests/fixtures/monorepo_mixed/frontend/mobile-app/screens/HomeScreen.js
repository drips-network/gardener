import React, { useState, useEffect } from 'react';
import {
    View,
    Text,
    FlatList,
    TouchableOpacity,
    StyleSheet,
    RefreshControl,
} from 'react-native';
import moment from 'moment';
import { ApiService } from '../services/ApiService';

export default function HomeScreen({ navigation }) {
    const [users, setUsers] = useState([]);
    const [refreshing, setRefreshing] = useState(false);
    const [lastUpdated, setLastUpdated] = useState(null);

    useEffect(() => {
        loadUsers();
    }, []);

    const loadUsers = async () => {
        try {
            const data = await ApiService.getUsers();
            setUsers(data);
            setLastUpdated(moment());
        } catch (error) {
            console.error('Failed to load users:', error);
        }
    };

    const onRefresh = async () => {
        setRefreshing(true);
        await loadUsers();
        setRefreshing(false);
    };

    const renderUser = ({ item }) => (
        <TouchableOpacity
            style={styles.userItem}
            onPress={() => navigation.navigate('User', { user: item })}
        >
            <Text style={styles.userName}>{item.name}</Text>
            <Text style={styles.userEmail}>{item.email}</Text>
        </TouchableOpacity>
    );

    return (
        <View style={styles.container}>
            {lastUpdated && (
                <Text style={styles.updateText}>
                    Updated {lastUpdated.fromNow()}
                </Text>
            )}
            <FlatList
                data={users}
                renderItem={renderUser}
                keyExtractor={item => item.id.toString()}
                refreshControl={
                    <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
                }
            />
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#f5f5f5',
    },
    updateText: {
        padding: 10,
        textAlign: 'center',
        color: '#666',
    },
    userItem: {
        backgroundColor: 'white',
        padding: 15,
        marginVertical: 5,
        marginHorizontal: 10,
        borderRadius: 8,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.2,
        shadowRadius: 1,
        elevation: 2,
    },
    userName: {
        fontSize: 16,
        fontWeight: 'bold',
    },
    userEmail: {
        fontSize: 14,
        color: '#666',
        marginTop: 4,
    },
});